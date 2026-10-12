"""Patient values used, web research context, clinical NLP notes and prior-assessment memory.

None of these may change a decision: they add traceability and context for the reviewer.
"""

import copy

from app.workflow.graph import run_eligibility
from tests.test_api import _patient, _upload


def _by_id(results):
    return {e.criterion_id: e for e in results}


def _run(pages, patient, **kwargs):
    return run_eligibility(run_id="t", trial_id="trial-t", pages=pages, patient_input=patient, **kwargs)


# --------------------------------------------------------------------------- patient values used


def test_patient_values_used_link_values_to_criteria(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_69_egfr28.json")["result"]
    used = {v.attribute: v for v in result.patient_values_used}
    assert used["egfr"].value.startswith("28") and "INC-02" in used["egfr"].criterion_ids
    assert used["age"].value.startswith("69") and "INC-01" in used["age"].criterion_ids
    assert used["egfr"].observed_at.isoformat() == "2026-09-25"
    assert any(v.attribute == "diagnosis" and "diabetes" in v.value.lower() for v in result.patient_values_used)


# --------------------------------------------------------------------------- web research


class FakeSearch:
    provider = "fake"

    def __init__(self, fail: bool = False):
        self.queries: list[str] = []
        self.fail = fail

    def search(self, query, max_results=3):
        self.queries.append(query)
        if self.fail:
            raise TimeoutError("search timed out")
        return [{"title": "KDIGO CKD staging", "url": "https://example.org/kdigo", "snippet": "G4: eGFR 15-29"}]


def test_web_research_attaches_context_without_changing_decision(renal_pages, load_patient):
    patient = load_patient("patient_69_egfr28.json")["profile"]
    baseline = _run(renal_pages, patient)["result"]
    search = FakeSearch()
    result = _run(renal_pages, patient, web_search=search)["result"]

    assert result.overall_status == baseline.overall_status == "NOT_ELIGIBLE"
    assert [(e.criterion_id, e.status) for e in result.exclusion_results] == \
        [(e.criterion_id, e.status) for e in baseline.exclusion_results]
    refs = [r for r in result.external_references if r.criterion_id == "EXC-01"]
    assert refs and refs[0].url == "https://example.org/kdigo" and refs[0].provider == "fake"
    # Only protocol wording is sent: no patient values, labels or diagnoses.
    for q in search.queries:
        assert "severe renal impairment" in q.lower() or "renal" in q.lower()
        assert "28" not in q and "69" not in q and "diabetes" not in q.lower()
    # A deterministic numeric failure (INC-02) is not a wording problem and is never searched.
    assert all(r.criterion_id != "INC-02" for r in result.external_references)


def test_web_research_failure_is_a_note_not_an_error(renal_pages, load_patient):
    state = _run(renal_pages, load_patient("patient_69_egfr28.json")["profile"], web_search=FakeSearch(fail=True))
    assert state.get("error") is None
    result = state["result"]
    assert result.external_references == []
    assert any("web search unavailable" in n for n in result.reviewer_notes)


def test_web_research_disabled_by_default(renal_pages, run_workflow):
    state = run_workflow(renal_pages, "patient_69_egfr28.json")
    assert state["result"].external_references == []
    log = next(entry for entry in state["logs"] if entry["node"] == "web_research")
    assert log["status"] == "completed" and log["summary"]["enabled"] is False


# --------------------------------------------------------------------------- clinical NLP


class FakeMatcher:
    """Stands in for the BioBERT matcher: links nephropathy wording to renal terms."""

    name = "fake-biobert"

    def similar(self, term, candidates):
        if "renal" not in term.lower():
            return []
        return [(c, 0.88) for c in candidates if "nephropathy" in c.lower()]


def test_clinical_nlp_flags_possible_match_but_keeps_unknown(renal_pages, load_patient):
    patient = copy.deepcopy(load_patient("patient_69_egfr28.json")["profile"])
    patient["diagnoses"].append({"name": "Progressive IgA nephropathy", "documented_at": "2026-06-01"})

    without = _by_id(_run(renal_pages, patient)["result"].exclusion_results)["EXC-01"]
    result = _run(renal_pages, patient, concept_matcher=FakeMatcher())["result"]
    severe = _by_id(result.exclusion_results)["EXC-01"]

    assert severe.status == without.status == "UNKNOWN"  # a similarity score never decides
    assert severe.requires_human_review is True
    note = next(n for n in severe.uncertainty_notes if n.startswith("Clinical NLP"))
    assert "Progressive IgA nephropathy" in note and "0.88" in note and "Not used to decide" in note
    assert result.overall_status == "NOT_ELIGIBLE"


def test_clinical_nlp_failure_never_breaks_evaluation(renal_pages, load_patient):
    class Broken:
        name = "broken"

        def similar(self, term, candidates):
            raise RuntimeError("model crashed")

    patient = copy.deepcopy(load_patient("patient_69_egfr28.json")["profile"])
    patient["diagnoses"].append({"name": "Progressive IgA nephropathy"})
    state = _run(renal_pages, patient, concept_matcher=Broken())
    assert state.get("error") is None
    assert _by_id(state["result"].exclusion_results)["EXC-01"].status == "UNKNOWN"


# --------------------------------------------------------------------------- persistent memory


def test_second_assessment_remembers_the_first(client, auth_headers, fixture_path, load_patient):
    h = auth_headers()
    trial = _upload(client, h, fixture_path)
    patient = _patient(client, h, load_patient)
    first = client.post("/api/eligibility/analyze", headers=h,
                        json={"trial_id": trial["id"], "patient_id": patient["id"]}).json()["run_id"]
    assert client.get(f"/api/eligibility/{first}", headers=h).json()["result"]["prior_assessment"] is None

    profile = load_patient("patient_69_egfr28.json")["profile"]
    profile["labs"][0]["value"] = 45  # eGFR improves
    assert client.patch(f"/api/patients/{patient['id']}", headers=h, json={"profile": profile}).status_code == 200
    second = client.post("/api/eligibility/analyze", headers=h,
                         json={"trial_id": trial["id"], "patient_id": patient["id"]}).json()["run_id"]

    result = client.get(f"/api/eligibility/{second}", headers=h).json()["result"]
    memory = result["prior_assessment"]
    assert memory["run_id"] == first and memory["overall_status"] == "NOT_ELIGIBLE"
    assert memory["patient_profile_version"] == 1
    assert "INC-02 UNSATISFIED -> SATISFIED" in memory["changed_criteria"]
    assert any(n.startswith("Previous assessment (profile v1) was NOT_ELIGIBLE") for n in result["reviewer_notes"])


def test_health_reports_backends(client):
    body = client.get("/api/health").json()
    assert body["storage_backend"] in {"file", "postgresql"}
    assert body["workflow_state"] == "memory"
    assert body["clinical_nlp"] == "disabled" and body["web_search"] == "disabled"
