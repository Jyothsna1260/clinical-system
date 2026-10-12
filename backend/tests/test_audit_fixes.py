"""Regression tests for the issues in AUDIT_REPORT.md (C1, C2, H1, H2, M1-M12, L1-L9).

Each test names the finding it guards. The acceptance case (age 69, eGFR 28) is re-checked here so
any eligibility-logic change that breaks it fails in this file too.
"""

import copy
import json

import pytest

from app.agents.patient_profile import normalize_patient
from app.agents.protocol_extraction import extract_with_llm, parse_rule, select_llm_pages
from app.engine.rule_evaluator import _combine, _semantic_payload, evaluate_criterion
from app.engine.vocabulary import canonical_lab, find_lab_in_text
from app.rag.pdf_loader import PageText
from app.schemas.clinical import Criterion, PatientProfileInput
from app.workflow.graph import run_eligibility
from tests.test_api import _patient, _upload


def _by_id(results):
    return {e.criterion_id: e for e in results}


def _run(pages, patient, **kw):
    return run_eligibility(run_id="t", trial_id="trial-t", pages=pages, patient_input=patient, **kw)


def _criterion(text: str, category: str = "exclusion") -> Criterion:
    parsed = parse_rule(text)
    prefix = "INC" if category == "inclusion" else "EXC"
    return Criterion(
        criterion_id=f"{prefix}-01", trial_id="t", category=category, original_text=text,
        normalized_rule=parsed.rule, secondary_rule=parsed.secondary if parsed.rule else None,
        rule_combinator=parsed.combinator if parsed.rule and parsed.secondary else None,
        required_attributes=parsed.required_attributes, source_page=1, source_excerpt=text,
        extraction_confidence=parsed.confidence,
    )


def _profile(labs, **kw) -> PatientProfileInput:
    return PatientProfileInput.model_validate({"as_of": "2026-10-01", "demographics": {"age": 60}, "labs": labs, **kw})


# --------------------------------------------------------------------------- acceptance stays intact


def test_acceptance_case_still_not_eligible_with_renal_trigger(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_69_egfr28.json")["result"]
    inc = _by_id(result.inclusion_results)
    assert result.overall_status == "NOT_ELIGIBLE"
    assert inc["INC-01"].status == "SATISFIED" and inc["INC-02"].status == "UNSATISFIED"
    trigger = result.silent_exclusion_triggers[0]
    assert trigger.domain == "renal" and {2, 3} <= {r.page for r in trigger.evidence_references}


# --------------------------------------------------------------------------- C1


def test_c1_newer_unconvertible_lab_blocks_older_value(renal_pages, load_patient):
    patient = load_patient("patient_all_pass.json")["profile"]
    assert _run(renal_pages, patient)["result"].overall_status == "ELIGIBLE"
    patient = copy.deepcopy(patient)
    patient["labs"].append({"name": "eGFR", "value": 28, "unit": "mL/min", "observed_at": patient["as_of"]})
    result = _run(renal_pages, patient)["result"]
    egfr = _by_id(result.inclusion_results)["INC-02"]
    assert egfr.status == "UNKNOWN"
    assert result.overall_status == "MORE_INFORMATION_REQUIRED"
    assert any(m.attribute == "egfr" and "could not be used" in m.reason for m in result.missing_information)


def test_c1_newer_undated_lab_blocks_older_value():
    p = normalize_patient(_profile([
        {"name": "eGFR", "value": 45, "unit": "mL/min/1.73m2", "observed_at": "2026-09-01"},
        {"name": "eGFR", "value": 28, "unit": "mL/min/1.73m2"},
    ]), ["egfr"])
    assert p.attributes["egfr"].status == "ambiguous"
    assert "undated" in p.attributes["egfr"].detail


def test_c1_older_unconvertible_lab_does_not_block_newer_value():
    p = normalize_patient(_profile([
        {"name": "eGFR", "value": 20, "unit": "mL/min", "observed_at": "2026-08-01"},
        {"name": "eGFR", "value": 45, "unit": "mL/min/1.73m2", "observed_at": "2026-09-20"},
    ]), ["egfr"])
    assert p.attributes["egfr"].status == "ok" and p.attributes["egfr"].value == 45


# --------------------------------------------------------------------------- C2


@pytest.mark.parametrize("op,a,b,expected", [
    ("and", True, True, True), ("and", True, None, None), ("and", False, None, False), ("and", True, False, False),
    ("or", False, False, False), ("or", False, None, None), ("or", True, None, True), ("or", None, None, None),
])
def test_c2_three_valued_combination(op, a, b, expected):
    assert _combine(op, a, b) is expected


def test_c2_or_exclusion_triggers_on_second_clause():
    c = _criterion("Creatinine > 1.5 mg/dL or creatinine clearance < 40 mL/min")
    assert c.normalized_rule.attribute == "creatinine" and c.secondary_rule.attribute == "crcl"
    assert c.rule_combinator == "or" and set(c.required_attributes) == {"creatinine", "crcl"}
    profile = normalize_patient(_profile([
        {"name": "Creatinine", "value": 1.2, "unit": "mg/dL", "observed_at": "2026-09-20"},
        {"name": "Creatinine clearance", "value": 30, "unit": "mL/min", "observed_at": "2026-09-20"},
    ]), c.required_attributes)
    outcome = evaluate_criterion(c, profile)
    assert outcome.result is True and outcome.attribute == "crcl"


def test_c2_or_exclusion_with_missing_second_clause_is_unknown_not_clear():
    c = _criterion("Creatinine > 1.5 mg/dL or creatinine clearance < 40 mL/min")
    profile = normalize_patient(_profile([
        {"name": "Creatinine", "value": 1.2, "unit": "mg/dL", "observed_at": "2026-09-20"},
    ]), c.required_attributes)
    outcome = evaluate_criterion(c, profile)
    assert outcome.result is None and outcome.attribute == "crcl"
    assert any("missing" in f.flag for f in profile.data_quality_flags if f.attribute == "crcl")


def test_c2_two_sided_bound_keeps_upper_limit_and_unit():
    c = _criterion("eGFR >= 30 and <= 90 mL/min/1.73m2", "inclusion")
    assert (c.normalized_rule.operator, c.secondary_rule.operator, c.rule_combinator) == ("gte", "lte", "and")
    assert c.normalized_rule.unit == "mL/min/1.73m2" and not c.review_reasons
    high = normalize_patient(_profile([{"name": "eGFR", "value": 120, "unit": "mL/min/1.73m2",
                                        "observed_at": "2026-09-20"}]), ["egfr"])
    assert evaluate_criterion(c, high).result is False
    mid = normalize_patient(_profile([{"name": "eGFR", "value": 60, "unit": "mL/min/1.73m2",
                                       "observed_at": "2026-09-20"}]), ["egfr"])
    assert evaluate_criterion(c, mid).result is True


def test_c2_shared_threshold_across_two_labs():
    c = _criterion("ALT or AST > 100 U/L")
    assert (c.normalized_rule.attribute, c.secondary_rule.attribute, c.rule_combinator) == ("alt", "ast", "or")


def test_c2_unparseable_second_clause_is_flagged_not_dropped():
    p = parse_rule("Creatinine > 1.5 mg/dL or creatinine clearance")
    assert p.rule is None and set(p.required_attributes) == {"creatinine", "crcl"}
    assert any("Compound criterion" in r for r in p.review_reasons)


def test_c2_unrelated_trailing_threshold_is_not_a_second_clause():
    p = parse_rule("eGFR at least 45 mL/min/1.73m2 and stable for at least 3 months")
    assert p.secondary is None and p.rule.value == 45


def test_c2_stored_single_clause_criteria_still_load():
    stored = _criterion("eGFR below 30 mL/min/1.73m2").model_dump(mode="json")
    del stored["secondary_rule"], stored["rule_combinator"]
    assert Criterion.model_validate(stored).secondary_rule is None


def test_lab_alias_prefers_specific_name():
    assert find_lab_in_text("creatinine clearance < 40 ml/min")[0] == "crcl"
    assert canonical_lab("Creatinine clearance (Cockcroft-Gault)") == "crcl"
    assert canonical_lab("Serum creatinine") == "creatinine"


# --------------------------------------------------------------------------- H1


@pytest.mark.parametrize("text", [
    "Chronic kidney disease stage 3 to 4", "CKD stage 3-4", "Stable dosage of 10 to 20 mg metformin",
    "Stage >= 3 heart failure", "Average systolic pressure 120 to 140",
])
def test_h1_words_containing_age_are_not_age_rules(text):
    p = parse_rule(text)
    assert p.rule is None or p.rule.attribute != "age"


@pytest.mark.parametrize("text,op", [
    ("Age 18 to 70 years inclusive", "between"), ("Aged 18 years or older", "gte"), ("Ages 18-65", "between"),
    ("At least 18 years of age", "gte"),
])
def test_h1_real_age_rules_still_parse(text, op):
    p = parse_rule(text)
    assert p.rule.attribute == "age" and p.rule.operator == op


# --------------------------------------------------------------------------- M1, M3


class FakeLLM:
    provider, model = "fake", "m"

    def __init__(self, criteria):
        self.criteria = criteria
        self.user_prompts: list[str] = []

    def complete_json(self, system, user, schema):
        self.user_prompts.append(user)
        return {"criteria": self.criteria}


def test_m1_llm_condition_criteria_do_not_create_missing_condition_flag():
    llm = FakeLLM([{"category": "exclusion", "original_text": "Severe renal impairment.", "source_page": 1,
                    "source_excerpt": "Severe renal impairment.", "attribute": "condition", "operator": "present",
                    "value": None, "value_terms": ["severe renal impairment"], "value_max": None, "unit": None,
                    "inclusive": None, "ambiguity_reason": None}])
    criteria = extract_with_llm([PageText(1, "Exclusion Criteria\n1. Severe renal impairment.")], "t", llm)
    assert criteria[0].required_attributes == ["condition:severe renal impairment"]
    profile = normalize_patient(PatientProfileInput.model_validate({"demographics": {"age": 69}}),
                                criteria[0].required_attributes)
    assert not any(f.attribute == "condition" for f in profile.data_quality_flags)


def test_m3_llm_receives_only_eligibility_pages():
    pages = [PageText(i, f"Section {i} background text") for i in range(1, 11)]
    pages[5] = PageText(6, "Inclusion Criteria\n1. Age 18 to 70 years")
    selected, note = select_llm_pages(pages)
    assert [p.page for p in selected] == [5, 6, 7]
    assert note and "5, 6, 7 of 10" in note


def test_m3_char_budget_caps_what_is_sent():
    pages = [PageText(i, "eligibility " + "x" * 1000) for i in range(1, 6)]
    selected, note = select_llm_pages(pages, budget=2500)
    assert len(selected) == 2 and note


# --------------------------------------------------------------------------- M2 / Q5


def test_q5_anthropic_client_uses_typed_beta_fallbacks():
    from app.services.llm import AnthropicLLM

    captured = {}

    class Block:
        type, text = "text", '{"ok": true}'

    class Response:
        stop_reason, content = "end_turn", [Block()]

    class Messages:
        def create(self, **kw):
            captured.update(kw)
            return Response()

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-opus-5-5"
    llm._client = type("C", (), {"beta": type("B", (), {"messages": Messages()})()})()
    assert llm.complete_json("s", "u", {"type": "object"}) == {"ok": True}
    assert captured["betas"] == ["server-side-fallback-2026-07-01"] and captured["fallbacks"] == "default"
    assert captured["output_config"]["format"]["type"] == "json_schema"


# --------------------------------------------------------------------------- M4


def test_m4_corrupt_index_is_rebuilt_not_fatal(tmp_path):
    from app.rag.chunker import chunk_pages
    from app.rag.index import build_index, load_index

    directory = tmp_path / "idx"
    directory.mkdir()
    (directory / "chunks.json").write_text('[{"chunk_id": "x", "trial', encoding="utf-8")  # half-written
    assert load_index(directory, False, "m") is None
    pages = [PageText(1, "Inclusion Criteria\n1. eGFR at least 30")]
    idx = build_index(chunk_pages(pages, "t", "d"), directory, False, "m")
    assert idx.kind == "keyword" and load_index(directory, False, "m") is not None
    assert not list(directory.glob("*.tmp"))


# --------------------------------------------------------------------------- M5, L9


def test_m5_too_many_pages_is_a_clear_error(client, auth_headers, fixture_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pdf_pages", 1)
    h = auth_headers()
    with open(fixture_path("protocol_renal.pdf"), "rb") as fh:
        r = client.post("/api/trials/upload", headers=h, files={"file": ("p.pdf", fh, "application/pdf")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "TOO_MANY_PAGES"


def test_l9_oversized_upload_rejected_from_content_length_with_cors(client, auth_headers):
    r = client.post("/api/trials/upload", headers={**auth_headers(), "Content-Length": str(500 * 1024 * 1024),
                                                   "Origin": "http://localhost:5173"}, content=b"x")
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# --------------------------------------------------------------------------- M6, L2, L5


def _start_run(client, h, fixture_path, load_patient):
    trial = _upload(client, h, fixture_path)
    patient = _patient(client, h, load_patient)
    return trial, patient


def test_m6_run_that_cannot_save_its_result_is_marked_failed(client, auth_headers, fixture_path, load_patient,
                                                             monkeypatch):
    from app.services import analysis

    monkeypatch.setattr(analysis, "persist_state", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    h = auth_headers()
    trial, patient = _start_run(client, h, fixture_path, load_patient)
    run_id = client.post("/api/eligibility/analyze", headers=h,
                         json={"trial_id": trial["id"], "patient_id": patient["id"]}).json()["run_id"]
    status = client.get(f"/api/eligibility/{run_id}/status", headers=h).json()
    assert status["status"] == "failed" and status["error"]["code"] == "ANALYSIS_INCOMPLETE"


def test_m6_interrupted_runs_are_failed_at_startup(client, auth_headers, fixture_path, load_patient):
    from datetime import timedelta

    from app.services.analysis import fail_interrupted_runs
    from app.storage import RunRecord, get_store, utcnow

    h = auth_headers()
    trial, patient = _start_run(client, h, fixture_path, load_patient)
    store = get_store()
    owner = store.trials.get(trial["id"]).owner_id
    run = store.runs.put(RunRecord(owner_id=owner, trial_id=trial["id"], document_id="d", protocol_version="v",
                                   patient_id=patient["id"], patient_profile_id="pp", patient_profile_version=1,
                                   status="running"))
    assert fail_interrupted_runs(store, older_than_minutes=30) == 0  # recent: may still be running
    store.runs.update(run.id, lambda r: None)
    # Age it past the cutoff (put() stamps updated_at, so check with a negative window instead).
    assert fail_interrupted_runs(store, older_than_minutes=-1) == 1
    failed = store.runs.get(run.id)
    assert failed.status == "failed" and failed.error["code"] == "ANALYSIS_INTERRUPTED"
    assert failed.updated_at > utcnow() - timedelta(minutes=1)


def test_l2_progress_store_failure_does_not_stop_the_run(renal_pages, load_patient):
    def broken_reporter(*args):
        raise ConnectionError("redis gone")

    state = _run(renal_pages, load_patient("patient_69_egfr28.json")["profile"], reporter=broken_reporter)
    assert state.get("error") is None and state["result"].overall_status == "NOT_ELIGIBLE"


def test_l5_agent_failure_message_does_not_leak_exception_text(renal_pages, load_patient, monkeypatch):
    from app.workflow import graph

    def boom(*a, **k):
        raise ValueError("secret internal detail")

    monkeypatch.setattr(graph, "detect_contradictions", boom)
    state = _run(renal_pages, load_patient("patient_69_egfr28.json")["profile"])
    err = state["error"]
    assert err["code"] == "AGENT_FAILURE" and "secret" not in err["message"]
    assert err["details"]["error_type"] == "ValueError"


# --------------------------------------------------------------------------- M9


def test_m9_semantic_payload_is_minimised(load_patient):
    patient = PatientProfileInput.model_validate(load_patient("patient_69_egfr28.json")["profile"])
    profile = normalize_patient(patient, ["egfr", "hba1c"])
    c = Criterion(criterion_id="INC-03", trial_id="t", category="inclusion",
                  original_text="Able to comply with kidney function monitoring", source_page=1,
                  source_excerpt="x", extraction_confidence=0.4)
    payload = _semantic_payload(c, profile)
    assert set(payload["labs"]) == {"egfr"}  # renal domain only; HbA1c is not sent
    assert payload["age"] == 69 and "data_quality_flags" not in payload


def test_m9_semantic_evaluation_can_be_turned_off(renal_pages, load_patient):
    calls = []

    class Spy:
        provider, model = "spy", "m"

        def complete_json(self, system, user, schema):
            if "<document type=\"patient\">" in user:  # semantic evaluation (patient data), not extraction
                calls.append(user)
                return {"answer": "yes", "explanation": "x"}
            return {"criteria": []}  # extraction: fall back to the rule-based extractor

    criteria_text = renal_pages[1]["text"] + "\n3. Able to comply with study visits."
    pages = copy.deepcopy(renal_pages)
    pages[1]["text"] = criteria_text
    patient = load_patient("patient_69_egfr28.json")["profile"]
    _run(pages, patient, llm=Spy(), semantic_evaluation=False)
    assert calls == []
    _run(pages, patient, llm=Spy())
    assert calls  # default behaviour unchanged: semantic criteria are sent when enabled


# --------------------------------------------------------------------------- M11


def test_m11_login_is_rate_limited(client, auth_headers, monkeypatch):
    from app.config import get_settings
    from app.security.rate_limit import reset_counter

    auth_headers("limited@example.org")
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 3)
    reset_counter()
    body = {"email": "limited@example.org", "password": "wrong-password-1"}
    codes = [client.post("/api/auth/login", json=body).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    assert client.post("/api/auth/login", json=body).json()["error"]["code"] == "RATE_LIMITED"


# --------------------------------------------------------------------------- M12, L4, L7


def test_m12_result_evidence_and_audit_are_typed_in_openapi(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"EligibilityResult", "RunEvidence", "RunAudit"} <= set(schemas)


def test_m12_legacy_result_shape_is_returned_as_saved(client, auth_headers, fixture_path, load_patient):
    from app.storage import get_store

    h = auth_headers()
    trial, patient = _start_run(client, h, fixture_path, load_patient)
    run_id = client.post("/api/eligibility/analyze", headers=h,
                         json={"trial_id": trial["id"], "patient_id": patient["id"]}).json()["run_id"]
    get_store().runs.update(run_id, lambda r: setattr(r, "result", {"legacy": True}))
    r = client.get(f"/api/eligibility/{run_id}", headers=h)
    assert r.status_code == 200 and r.json()["result"] == {"legacy": True}


def test_l4_index_failure_does_not_overwrite_extraction_error(client, auth_headers, fixture_path, monkeypatch):
    from app.services import trials
    from app.storage import get_store

    h = auth_headers()
    trial = _upload(client, h, fixture_path)
    doc = trials.latest_document(get_store(), get_store().trials.get(trial["id"]))
    monkeypatch.setattr(trials, "get_or_build_index", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    trials.build_index_task(trial["id"], doc.id)
    stored = get_store().trials.get(trial["id"])
    assert stored.index_status == "error" and stored.index_error["code"] == "INDEX_FAILED"
    assert stored.error is None and stored.status == "ready"


def test_l7_health_reports_upload_limits(client):
    body = client.get("/api/health").json()
    assert body["max_upload_mb"] == 20 and body["max_pdf_pages"] == 300
    json.dumps(body)
