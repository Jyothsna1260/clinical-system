"""Agent E - Contradiction / Silent Exclusion Trigger detection.

Groups criteria into clinical domains with a keyword/attribute map. A Silent Exclusion
Trigger is raised when the patient passes some inclusion criteria (so looks eligible at a
glance) but, in one clinical domain, a related inclusion is UNSATISFIED or a related
exclusion is TRIGGERED or UNKNOWN. Every trigger must carry at least one patient value
and one protocol citation; otherwise it is not created.

Also records conflicting rules, inconsistent patient values and missing data.
"""

from dataclasses import dataclass, field

from app.engine.vocabulary import domain_attributes, domains_for, label
from app.schemas.clinical import (
    Conflict,
    Criterion,
    CriterionEvaluation,
    EvidenceReference,
    MissingInformation,
    NormalizedProfile,
    PatientFinding,
    SilentExclusionTrigger,
)


@dataclass
class ContradictionReport:
    triggers: list[SilentExclusionTrigger] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    missing_information: list[MissingInformation] = field(default_factory=list)


def criterion_domains(c: Criterion) -> set[str]:
    attrs = [c.normalized_rule.attribute] if c.normalized_rule else []
    return domains_for(c.original_text, attrs + c.required_attributes)


def _dedupe_refs(refs: list[EvidenceReference]) -> list[EvidenceReference]:
    seen, out = set(), []
    for r in refs:
        key = (r.page, r.excerpt)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return sorted(out, key=lambda r: r.page)


def _domain_findings(domain: str, profile: NormalizedProfile, evals: list[CriterionEvaluation]) -> list[PatientFinding]:
    findings: list[PatientFinding] = []
    for attr in domain_attributes(domain):
        av = profile.attributes.get(attr)
        if av is None:
            continue
        if av.value is not None:
            unit = f" {av.unit}" if av.unit else ""
            findings.append(PatientFinding(attribute=attr, value=f"{av.value:g}{unit}", observed_at=av.observed_at))
        elif av.status == "conflicting" and av.observations:
            values = ", ".join(f"{o.value:g}" for o in av.observations if o.observed_at == av.observed_at)
            findings.append(PatientFinding(attribute=attr, value=f"conflicting: {values}", observed_at=av.observed_at))
    for e in evals:
        if e.attribute == "condition" and e.patient_value and e.status in {"TRIGGERED", "SATISFIED"}:
            findings.append(PatientFinding(attribute="condition", value=e.patient_value))
    return findings


def _rule_conflicts(criteria: list[Criterion]) -> list[Conflict]:
    """Inclusion and exclusion numeric rules on the same attribute that no patient could satisfy."""
    conflicts: list[Conflict] = []
    numeric = [c for c in criteria if c.normalized_rule and c.normalized_rule.operator in {"gt", "gte", "lt", "lte"}]
    for inc in (c for c in numeric if c.category == "inclusion"):
        for exc in (c for c in numeric if c.category == "exclusion"):
            ri, re_ = inc.normalized_rule, exc.normalized_rule
            assert ri and re_
            if ri.attribute != re_.attribute or ri.unit != re_.unit:
                continue
            vi, ve = float(ri.value), float(re_.value)  # type: ignore[arg-type]
            # inclusion requires x >= vi (or >), exclusion removes x >= ve (or >): if ve <= vi, nothing remains.
            both_lower = ri.operator in {"gt", "gte"} and re_.operator in {"gt", "gte"}
            both_upper = ri.operator in {"lt", "lte"} and re_.operator in {"lt", "lte"}
            if (both_lower and ve <= vi) or (both_upper and ve >= vi):
                impossible = True
            else:
                impossible = False
            if impossible:
                conflicts.append(Conflict(
                    conflict_type="conflicting_rules",
                    description=(
                        f"{inc.criterion_id} requires {label(ri.attribute)} {ri.operator} {vi:g} but "
                        f"{exc.criterion_id} excludes {label(re_.attribute)} {re_.operator} {ve:g}; "
                        "no patient can satisfy both. Protocol wording needs review."
                    ),
                    criterion_ids=[inc.criterion_id, exc.criterion_id],
                    attributes=[ri.attribute],
                ))
    for cat in ("inclusion", "exclusion"):
        by_key: dict[tuple[str, str], list[Criterion]] = {}
        for c in numeric:
            if c.category == cat:
                by_key.setdefault((c.normalized_rule.attribute, c.normalized_rule.operator), []).append(c)  # type: ignore[union-attr]
        for (attr, op), group in by_key.items():
            values = {float(c.normalized_rule.value) for c in group}  # type: ignore[union-attr, arg-type]
            if len(values) > 1:
                conflicts.append(Conflict(
                    conflict_type="conflicting_rules",
                    description=f"Multiple {cat} thresholds for {label(attr)} ({op}): "
                                + ", ".join(f"{v:g}" for v in sorted(values)) + ".",
                    criterion_ids=[c.criterion_id for c in group],
                    attributes=[attr],
                ))
    return conflicts


def detect_contradictions(
    criteria: list[Criterion],
    inclusion_results: list[CriterionEvaluation],
    exclusion_results: list[CriterionEvaluation],
    profile: NormalizedProfile,
) -> ContradictionReport:
    report = ContradictionReport()
    by_id = {c.criterion_id: c for c in criteria}
    evals = {e.criterion_id: e for e in inclusion_results + exclusion_results}
    satisfied = [e for e in inclusion_results if e.status == "SATISFIED"]

    domains: dict[str, list[str]] = {}
    for c in criteria:
        for d in criterion_domains(c):
            domains.setdefault(d, []).append(c.criterion_id)

    if satisfied:
        for n, (domain, ids) in enumerate(sorted(domains.items()), start=1):
            domain_evals = [evals[i] for i in ids if i in evals]
            failing_inc = [e for e in domain_evals if e.category == "inclusion" and e.status == "UNSATISFIED"]
            triggered = [e for e in domain_evals if e.category == "exclusion" and e.status == "TRIGGERED"]
            unknown_exc = [e for e in domain_evals if e.category == "exclusion" and e.status == "UNKNOWN"]
            if not (failing_inc or triggered or unknown_exc):
                continue
            findings = _domain_findings(domain, profile, domain_evals)
            passed_same_domain = [e for e in satisfied if e.criterion_id in ids]
            passed = passed_same_domain or satisfied
            involved = passed + failing_inc + triggered + unknown_exc
            refs = _dedupe_refs([r for e in involved for r in e.evidence_references])
            if not findings or not refs:
                continue  # never create a trigger without a patient value and a protocol citation

            parts = [
                "Patient satisfies "
                + ", ".join(f"{e.criterion_id} ({by_id[e.criterion_id].original_text.rstrip('.')})" for e in passed)
                + f", but in the {domain} domain:"
            ]
            for e in failing_inc:
                parts.append(f"{e.criterion_id} is UNSATISFIED "
                             f"(patient {e.patient_value}; required {e.expected_condition}).")
            for e in triggered:
                parts.append(f"{e.criterion_id} is TRIGGERED ({e.patient_value}).")
            uncertainties = []
            for e in unknown_exc:
                text = by_id[e.criterion_id].original_text.rstrip(".")
                confirm = next((n_ for n_ in e.uncertainty_notes if "not confirmed by" in n_), None)
                detail = confirm or "requires clinical confirmation"
                reason = f": {confirm.rstrip('.')}" if confirm else ""
                parts.append(f"{e.criterion_id} ('{text}') is UNKNOWN{reason}; requires clinical confirmation.")
                uncertainties.append(f"{e.criterion_id}: {detail}")
            pages = sorted({r.page for r in refs})
            parts.append("Cited protocol pages: " + ", ".join(str(p) for p in pages) + ".")

            deterministic_fail = any(e.comparison_method == "deterministic" for e in failing_inc + triggered)
            priority = "high" if deterministic_fail else "medium" if unknown_exc else "low"
            confidences = [by_id[e.criterion_id].extraction_confidence for e in failing_inc + triggered + unknown_exc]
            report.triggers.append(SilentExclusionTrigger(
                trigger_id=f"SET-{n:02d}",
                domain=domain,
                inclusion_criterion_ids=[e.criterion_id for e in passed],
                exclusion_criterion_ids=[e.criterion_id for e in triggered + unknown_exc],
                related_failing_criterion_ids=[e.criterion_id for e in failing_inc + triggered],
                patient_findings=findings,
                explanation=" ".join(parts),
                evidence_references=refs,
                review_priority=priority,
                confidence=round(min(confidences) if confidences else 0.5, 2),
                unresolved_uncertainties=uncertainties,
            ))

    report.conflicts.extend(_rule_conflicts(criteria))
    for flag in profile.data_quality_flags:
        if flag.flag == "conflicting":
            report.conflicts.append(Conflict(
                conflict_type="inconsistent_patient_values",
                description=flag.detail,
                criterion_ids=[e.criterion_id for e in evals.values() if e.attribute == flag.attribute],
                attributes=[flag.attribute],
            ))

    missing: dict[str, MissingInformation] = {}
    for e in inclusion_results + exclusion_results:
        if e.status != "UNKNOWN":
            continue
        attr = e.attribute or "clinical_review"
        av = profile.attributes.get(attr) if e.attribute else None
        if av is not None and av.status in {"missing", "stale", "ambiguous", "conflicting"}:
            reason = av.detail or f"{label(attr)} {av.status}"
        elif attr == "condition":
            reason = "Condition not documented as present or absent; requires clinical confirmation."
        elif e.attribute is None:
            reason = "Criterion requires clinical/semantic review."
        else:
            reason = e.uncertainty_notes[0] if e.uncertainty_notes else "Value could not be evaluated."
        key = f"{attr}:{reason}"
        if key in missing:
            missing[key].criterion_ids.append(e.criterion_id)
        else:
            missing[key] = MissingInformation(attribute=attr, criterion_ids=[e.criterion_id], reason=reason)
    report.missing_information = list(missing.values())
    return report
