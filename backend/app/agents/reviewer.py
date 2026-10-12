"""Agent F - Decision / Reviewer.

1. Evidence gate: any decisive evaluation without a protocol citation is downgraded to
   UNKNOWN; any Silent Exclusion Trigger without evidence or patient findings is dropped.
2. Conservative decision table:
   - any inclusion UNSATISFIED with deterministic evidence, or any exclusion TRIGGERED
     with evidence -> NOT_ELIGIBLE (a proven exclusion always wins);
   - else any UNKNOWN, unresolved conflict, or semantic-model judgement -> MORE_INFORMATION_REQUIRED;
   - else ELIGIBLE (every inclusion SATISFIED, no exclusion TRIGGERED, no material uncertainty).
3. Traceability: the patient values used (with their normalization trace and the criteria they
   decided) and, from persistent memory, what changed since the previous assessment.
"""

from datetime import datetime, timezone

from app.agents.contradiction import ContradictionReport
from app.config import HUMAN_REVIEW_NOTICE
from app.engine.vocabulary import label
from app.schemas.clinical import (
    CriterionEvaluation,
    DecisiveEvidence,
    EligibilityResult,
    NormalizedProfile,
    PatientValueUsed,
    PriorAssessment,
    SilentExclusionTrigger,
)


def _evidence_gate(evals: list[CriterionEvaluation], notes: list[str]) -> list[CriterionEvaluation]:
    out = []
    for e in evals:
        if e.status != "UNKNOWN" and not e.evidence_references:
            notes.append(f"{e.criterion_id}: {e.status} finding had no verifiable protocol citation and was downgraded to UNKNOWN.")
            e = e.model_copy(update={
                "status": "UNKNOWN",
                "comparison_method": "not_evaluable",
                "requires_human_review": True,
                "uncertainty_notes": e.uncertainty_notes + ["Downgraded: no verifiable protocol citation."],
            })
        out.append(e)
    return out


def _decisive(e: CriterionEvaluation) -> DecisiveEvidence:
    return DecisiveEvidence(
        criterion_id=e.criterion_id,
        status=e.status,
        patient_value=e.patient_value,
        expected_condition=e.expected_condition,
        evidence_references=e.evidence_references,
    )


def review_and_decide(
    run_id: str,
    protocol_version: str,
    inclusion_results: list[CriterionEvaluation],
    exclusion_results: list[CriterionEvaluation],
    report: ContradictionReport,
    analyzed_at: datetime | None = None,
) -> EligibilityResult:
    notes: list[str] = []
    inclusion = _evidence_gate(inclusion_results, notes)
    exclusion = _evidence_gate(exclusion_results, notes)

    triggers: list[SilentExclusionTrigger] = []
    for t in report.triggers:
        if t.evidence_references and t.patient_findings:
            triggers.append(t)
        else:
            notes.append(f"{t.trigger_id} dropped: missing evidence or patient findings.")

    failed_inc = [e for e in inclusion if e.status == "UNSATISFIED" and e.comparison_method == "deterministic"]
    triggered_exc = [e for e in exclusion if e.status == "TRIGGERED"]
    unknown = [e for e in inclusion + exclusion if e.status == "UNKNOWN"]
    semantic = [e for e in inclusion + exclusion if e.comparison_method == "semantic_llm" and e.status != "UNKNOWN"]
    soft_fail_inc = [e for e in inclusion if e.status == "UNSATISFIED" and e.comparison_method != "deterministic"]

    if failed_inc or triggered_exc:
        status = "NOT_ELIGIBLE"
        decisive = failed_inc + triggered_exc
        reasons = [f"{e.criterion_id} UNSATISFIED: {e.explanation}" for e in failed_inc]
        reasons += [f"{e.criterion_id} TRIGGERED: {e.explanation}" for e in triggered_exc]
        explanation = "Not eligible. " + " ".join(reasons)
        if unknown:
            explanation += (
                f" {len(unknown)} other criterion/criteria remain UNKNOWN and are listed for review, "
                "but they cannot change this outcome."
            )
    elif unknown or report.conflicts or semantic or soft_fail_inc or not inclusion:
        status = "MORE_INFORMATION_REQUIRED"
        decisive = unknown + semantic + soft_fail_inc
        reasons = [f"{e.criterion_id} {e.status}: {e.explanation}" for e in unknown]
        reasons += [f"{e.criterion_id} decided by semantic model only and requires confirmation." for e in semantic + soft_fail_inc]
        reasons += [f"Conflict: {c.description}" for c in report.conflicts]
        if not inclusion:
            reasons.append("No inclusion criteria were evaluated.")
        explanation = "More information required before eligibility can be determined. " + " ".join(reasons)
    else:
        status = "ELIGIBLE"
        decisive = inclusion + exclusion
        explanation = (
            f"All {len(inclusion)} inclusion criteria are SATISFIED and none of the {len(exclusion)} exclusion "
            "criteria are TRIGGERED, with no unresolved uncertainty."
        )

    if triggers:
        explanation += f" {len(triggers)} Silent Exclusion Trigger(s) identified: " + " ".join(t.explanation for t in triggers)
    explanation += " " + HUMAN_REVIEW_NOTICE

    for e in inclusion + exclusion:
        if e.status != "UNKNOWN" and any("not defined numerically" in n or "inclusive" in n for n in e.uncertainty_notes):
            notes.append(f"{e.criterion_id}: protocol wording is flagged as ambiguous; outcome relied on explicit documentation or an unambiguous value.")

    return EligibilityResult(
        run_id=run_id,
        overall_status=status,  # type: ignore[arg-type]
        inclusion_results=inclusion,
        exclusion_results=exclusion,
        silent_exclusion_triggers=triggers,
        missing_information=report.missing_information,
        unresolved_conflicts=report.conflicts,
        decisive_evidence=[_decisive(e) for e in decisive],
        final_explanation=explanation.strip(),
        human_review_notice=HUMAN_REVIEW_NOTICE,
        protocol_version=protocol_version,
        analyzed_at=analyzed_at or datetime.now(timezone.utc),
        reviewer_notes=notes,
    )


# --------------------------------------------------------------------------- traceability


def _fmt(value: float, unit: str | None) -> str:
    return f"{value:g} {unit}".strip() if unit else f"{value:g}"


def patient_values_used(profile: NormalizedProfile, evaluations: list[CriterionEvaluation]) -> list[PatientValueUsed]:
    """Every patient value the agents compared against the protocol, linked to the criteria it decided."""
    by_attr: dict[str, list[str]] = {}
    for e in evaluations:
        if e.attribute:
            by_attr.setdefault(e.attribute, []).append(e.criterion_id)

    out: list[PatientValueUsed] = []
    for attr, criterion_ids in by_attr.items():
        av = profile.attributes.get(attr)
        if av is None:
            continue
        source = None
        if av.observations:
            obs = av.observations[0]
            converted = obs.original_unit != obs.unit or obs.original_value != obs.value
            source = f"{obs.source_name} {_fmt(obs.original_value, obs.original_unit)}" + (" (converted)" if converted else "")
        out.append(PatientValueUsed(
            attribute=attr, label=label(attr),
            value=_fmt(av.value, av.unit) if av.value is not None else "Not documented",
            observed_at=av.observed_at, status=av.status, source=source, criterion_ids=criterion_ids,
        ))

    condition_ids = by_attr.get("condition", []) + [cid for a, ids in by_attr.items() if a.startswith("event:") for cid in ids]
    records = [("diagnosis", d.name, d.documented_at) for d in profile.diagnoses]
    records += [("medication", m.name, m.start_date) for m in profile.medications]
    records += [("history", h.condition, None) for h in profile.history]
    evals = {e.criterion_id: e for e in evaluations}
    for kind, name, when in records:
        used_by = [cid for cid in condition_ids if name.lower() in (evals[cid].patient_value or "").lower()]
        value = name
        if kind == "history":
            present = next((h.present for h in profile.history if h.condition == name), None)
            value = f"{name}: {'present' if present else 'absent' if present is False else 'not stated'}"
        out.append(PatientValueUsed(attribute=kind, label=kind.capitalize(), value=value, observed_at=when,
                                    criterion_ids=used_by))
    return out


def compare_with_prior(prior: dict | None, overall_status: str,
                       evaluations: list[CriterionEvaluation]) -> tuple[PriorAssessment | None, list[str]]:
    """Persistent memory: what changed since the previous assessment of this patient for this trial."""
    if not prior:
        return None, []
    before = prior.get("criterion_statuses") or {}
    changed = [f"{e.criterion_id} {before[e.criterion_id]} -> {e.status}"
               for e in evaluations if e.criterion_id in before and before[e.criterion_id] != e.status]
    memory = PriorAssessment(
        run_id=prior["run_id"], overall_status=prior.get("overall_status"), analyzed_at=prior.get("analyzed_at"),
        patient_profile_version=prior["patient_profile_version"], protocol_version=prior["protocol_version"],
        changed_criteria=changed,
    )
    note = (f"Previous assessment (profile v{memory.patient_profile_version}) was {memory.overall_status}; "
            f"now {overall_status}.")
    note += f" Changed: {', '.join(changed)}." if changed else " No criterion outcome changed."
    return memory, [note]
