"""End-to-end agent decisions through the LangGraph workflow (offline)."""

from app.agents.contradiction import ContradictionReport
from app.agents.patient_profile import normalize_patient
from app.agents.reviewer import review_and_decide
from app.engine.rule_evaluator import evaluate_criterion
from app.schemas.clinical import Criterion, CriterionEvaluation, NormalizedProfile, PatientProfileInput


def _by_id(results):
    return {e.criterion_id: e for e in results}


def test_all_criteria_pass_is_eligible(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_all_pass.json")["result"]
    assert result.overall_status == "ELIGIBLE", result.final_explanation
    assert all(e.status == "SATISFIED" for e in result.inclusion_results)
    assert all(e.status == "NOT_TRIGGERED" for e in result.exclusion_results)
    assert result.silent_exclusion_triggers == []
    assert result.human_review_required is True


def test_missing_egfr_requires_more_information(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_missing_egfr.json")["result"]
    assert result.overall_status == "MORE_INFORMATION_REQUIRED"
    assert _by_id(result.inclusion_results)["INC-02"].status == "UNKNOWN"
    assert any(m.attribute == "egfr" for m in result.missing_information)


def test_conflicting_egfr_requires_more_information_with_conflict(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_conflicting_egfr.json")["result"]
    assert result.overall_status == "MORE_INFORMATION_REQUIRED"
    assert _by_id(result.inclusion_results)["INC-02"].status == "UNKNOWN"
    conflicts = [c for c in result.unresolved_conflicts if c.conflict_type == "inconsistent_patient_values"]
    assert conflicts and "egfr" in conflicts[0].attributes
    assert "INC-02" in conflicts[0].criterion_ids


def test_unknown_is_never_satisfied(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_missing_egfr.json")["result"]
    for e in result.inclusion_results + result.exclusion_results:
        if e.patient_value is None and e.attribute not in (None, "condition"):
            assert e.status == "UNKNOWN"


def test_undocumented_condition_is_unknown_not_absent(renal_pages, run_workflow):
    result = run_workflow(renal_pages, "patient_69_egfr28.json")["result"]
    exc = _by_id(result.exclusion_results)
    assert exc["EXC-01"].status == "UNKNOWN"
    assert exc["EXC-02"].status == "NOT_TRIGGERED"  # pregnancy not applicable to a male patient
    assert "requires clinical confirmation" in exc["EXC-01"].explanation.lower()


def test_proven_exclusion_wins_over_passing_inclusion(renal_pages, run_workflow, load_patient):
    from app.workflow.graph import run_eligibility

    patient = load_patient("patient_all_pass.json")["profile"]
    patient["diagnoses"].append({"name": "Pregnancy", "documented_at": "2026-09-01"})
    patient["history"] = [h for h in patient["history"] if h["condition"] != "Pregnancy"]
    result = run_eligibility(run_id="r", trial_id="t", pages=renal_pages, patient_input=patient)["result"]
    assert all(e.status == "SATISFIED" for e in result.inclusion_results)
    assert _by_id(result.exclusion_results)["EXC-02"].status == "TRIGGERED"
    assert result.overall_status == "NOT_ELIGIBLE"


class _BadLLM:
    provider, model = "fake", "fake"

    def complete_json(self, system, user, schema):
        return {"answer": "definitely", "explanation": 42}  # fails schema validation


class _GoodLLM:
    provider, model = "fake", "fake"

    def complete_json(self, system, user, schema):
        return {"answer": "yes", "explanation": "Consent documented."}


def _semantic_criterion() -> Criterion:
    return Criterion(criterion_id="INC-03", trial_id="t", category="inclusion",
                     original_text="Able to provide written informed consent.", normalized_rule=None,
                     source_page=2, source_excerpt="Able to provide written informed consent.",
                     extraction_confidence=0.4, requires_human_review=True)


def _profile() -> NormalizedProfile:
    return normalize_patient(PatientProfileInput.model_validate({"as_of": "2026-10-01", "demographics": {"age": 40}}))


def test_invalid_llm_json_gives_unknown_not_crash():
    outcome = evaluate_criterion(_semantic_criterion(), _profile(), _BadLLM())
    assert outcome.result is None and outcome.method == "not_evaluable"


def test_semantic_llm_result_is_not_decisive_alone():
    outcome = evaluate_criterion(_semantic_criterion(), _profile(), _GoodLLM())
    assert outcome.result is True and outcome.method == "semantic_llm"
    ev = CriterionEvaluation(criterion_id="INC-03", category="inclusion", status="SATISFIED",
                             original_text="x", expected_condition="x", comparison_method="semantic_llm",
                             explanation="x", evidence_references=[{"page": 2, "excerpt": "x"}])
    result = review_and_decide("r", "v1", [ev], [], ContradictionReport())
    assert result.overall_status == "MORE_INFORMATION_REQUIRED"


def test_reviewer_downgrades_findings_without_evidence():
    ev = CriterionEvaluation(criterion_id="INC-01", category="inclusion", status="UNSATISFIED",
                             original_text="x", expected_condition="x", comparison_method="deterministic",
                             explanation="x", evidence_references=[])
    result = review_and_decide("r", "v1", [ev], [], ContradictionReport())
    assert result.inclusion_results[0].status == "UNKNOWN"
    assert result.overall_status == "MORE_INFORMATION_REQUIRED"
    assert result.reviewer_notes


def test_workflow_error_for_unreadable_protocol(run_workflow):
    state = run_workflow([{"page": 1, "text": "   "}], "patient_all_pass.json")
    assert state["error"]["code"] == "UNREADABLE_PROTOCOL"
    assert "result" not in state or state.get("result") is None


def test_workflow_error_for_zero_criteria(run_workflow):
    state = run_workflow([{"page": 1, "text": "A protocol synopsis without any criteria."}], "patient_all_pass.json")
    assert state["error"]["code"] == "NO_CRITERIA"


def test_missing_patient_data_continues_as_unknown(renal_pages):
    from app.workflow.graph import run_eligibility

    state = run_eligibility(run_id="r", trial_id="t", pages=renal_pages, patient_input={})
    assert state.get("error") is None
    assert state["result"].overall_status == "MORE_INFORMATION_REQUIRED"


def test_node_logs_recorded(renal_pages, run_workflow):
    events = []
    state = run_workflow(renal_pages, "patient_69_egfr28.json",
                         reporter=lambda node, status, *_: events.append((node, status)))
    nodes = {entry["node"] for entry in state["logs"]}
    expected = {"inclusion_matching", "exclusion_detection", "detect_contradictions", "review_and_decide", "persist"}
    assert expected <= nodes
    assert ("review_and_decide", "completed") in events
