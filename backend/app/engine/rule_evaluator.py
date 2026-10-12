"""Evaluate one criterion against a normalized patient profile.

Shared by the Inclusion Matching and Exclusion Detection agents. The result is
tri-state: True (rule condition holds), False (it does not), None (cannot be decided).
UNKNOWN is never collapsed into True or False.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.engine.comparators import compare, describe
from app.engine.dates import within_days
from app.engine.units import UnitConversionError, convert
from app.engine.vocabulary import (
    SEX_SPECIFIC_FEMALE_CONDITIONS,
    canonical_condition,
    condition_matches,
    domain_attributes,
    domains_for,
    label,
    normalize_text,
)
from app.nlp.clinical import ConceptMatcher
from app.schemas.clinical import Criterion, NormalizedProfile, NormalizedRule
from app.services.llm import UNTRUSTED_DATA_RULE, LLMClient, LLMError

log = logging.getLogger(__name__)


@dataclass
class RuleOutcome:
    result: bool | None
    patient_value: str | None
    expected: str
    method: Literal["deterministic", "semantic_llm", "not_evaluable"]
    explanation: str
    notes: list[str] = field(default_factory=list)
    attribute: str | None = None


class _SemanticAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Literal["yes", "no", "unknown"]
    explanation: str


SEMANTIC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "explanation"],
    "properties": {
        "answer": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "explanation": {"type": "string"},
    },
}


def _fmt_value(value: float, unit: str | None) -> str:
    return f"{value:g} {unit}".strip() if unit else f"{value:g}"


def _related_lab_summary(criterion: Criterion, profile: NormalizedProfile) -> list[tuple[str, str]]:
    """Lab values in the same clinical domain as a non-numeric criterion."""
    out = []
    for domain in sorted(domains_for(criterion.original_text)):
        for attr in domain_attributes(domain):
            av = profile.attributes.get(attr)
            if av and av.value is not None:
                when = f" on {av.observed_at}" if av.observed_at else ""
                out.append((attr, f"{label(attr)} {_fmt_value(av.value, av.unit)}{when}"))
    return out


def _evaluate_numeric(rule: NormalizedRule, profile: NormalizedProfile) -> RuleOutcome:
    attr = rule.attribute
    expected = describe(rule)
    av = profile.attributes.get(attr)
    if av is None or av.status == "missing":
        return RuleOutcome(None, None, expected, "not_evaluable",
                           f"{label(attr)} is not documented in the patient profile; "
                           "the criterion cannot be evaluated.",
                           [f"Missing value: {label(attr)}."], attr)
    if av.status == "conflicting":
        return RuleOutcome(None, None, expected, "not_evaluable",
                           f"{av.detail} The criterion cannot be evaluated until the conflict is resolved.",
                           [av.detail or "Conflicting values."], attr)
    if av.value is None:
        return RuleOutcome(None, None, expected, "not_evaluable",
                           av.detail or f"{label(attr)} value is not usable.", [av.detail or ""], attr)
    patient_value = _fmt_value(av.value, av.unit)
    if av.status in {"stale", "ambiguous"}:
        return RuleOutcome(None, patient_value, expected, "not_evaluable",
                           f"{av.detail} A current, dated value is required before this criterion can be decided.",
                           [av.detail or ""], attr)

    threshold_rule = rule
    if rule.unit and av.unit and rule.unit != av.unit:
        try:
            update = {"value": convert(attr, float(rule.value), rule.unit, av.unit)}  # type: ignore[arg-type]
            if rule.value_max is not None:
                update["value_max"] = convert(attr, rule.value_max, rule.unit, av.unit)
            threshold_rule = rule.model_copy(update={**update, "unit": av.unit})
        except UnitConversionError as exc:
            return RuleOutcome(None, patient_value, expected, "not_evaluable",
                               f"Protocol unit {rule.unit} cannot be reconciled with patient unit {av.unit}: {exc}",
                               [str(exc)], attr)

    result = compare(av.value, threshold_rule)
    when = f" (observed {av.observed_at})" if av.observed_at and attr != "age" else ""
    if result is None:
        return RuleOutcome(None, patient_value, expected, "deterministic",
                           f"Patient {label(attr)} {patient_value} lies exactly on a boundary and the protocol "
                           "does not "
                           "state whether the bound is inclusive.",
                           ["Boundary inclusivity not stated in protocol."], attr)
    verb = "meets" if result else "does not meet"
    return RuleOutcome(result, patient_value, expected, "deterministic",
                       f"Patient {label(attr)} {patient_value}{when} {verb} the condition {expected}.", [], attr)


def _term_status(term: str, profile: NormalizedProfile) -> tuple[bool | None, str]:
    for dx in profile.diagnoses:
        if condition_matches(term, dx.name):
            when = f" (documented {dx.documented_at})" if dx.documented_at else ""
            return True, f"documented diagnosis '{dx.name}'{when}"
    explicit_absent = None
    for h in profile.history:
        if condition_matches(term, h.condition):
            if h.present is True:
                return True, f"history records '{h.condition}' as present"
            if h.present is False:
                explicit_absent = f"history explicitly records '{h.condition}' as absent"
    if explicit_absent:
        return False, explicit_absent
    if canonical_condition(term) in SEX_SPECIFIC_FEMALE_CONDITIONS and profile.sex == "male":
        return False, f"'{term}' does not apply to a patient documented as male"
    return None, f"'{term}' is neither documented nor explicitly recorded as absent"


def _possible_matches(terms: list[str], profile: NormalizedProfile,
                      matcher: ConceptMatcher | None) -> list[str]:
    """Clinical-NLP notes for patient records that may correspond to an unresolved condition term."""
    if matcher is None:
        return []
    records = {dx.name: f"documented diagnosis '{dx.name}'" for dx in profile.diagnoses}
    records.update({h.condition: f"history item '{h.condition}'" for h in profile.history if h.present is not False})
    notes = []
    for term in terms:
        try:
            hits = matcher.similar(term, list(records))
        except Exception as exc:  # the matcher is advisory; never fail an evaluation over it
            log.warning("clinical NLP matching failed for %r: %s", term, exc)
            return []
        for name, score in hits[:2]:
            notes.append(
                f"Clinical NLP ({matcher.name}, similarity {score:.2f}): {records[name]} may correspond to "
                f"'{term}'. Not used to decide; requires clinical confirmation."
            )
    return notes


def _evaluate_condition(criterion: Criterion, profile: NormalizedProfile,
                        matcher: ConceptMatcher | None = None) -> RuleOutcome:
    rule = criterion.normalized_rule
    assert rule is not None
    terms = rule.value if isinstance(rule.value, list) else [str(rule.value)]
    expected = describe(rule)
    statuses = [(t, *_term_status(t, profile)) for t in terms]
    present = [s for s in statuses if s[1] is True]
    if present:
        result: bool | None = True
        reasons = [s[2] for s in present]
    elif all(s[1] is False for s in statuses):
        result = False
        reasons = [s[2] for s in statuses]
    else:
        result = None
        reasons = [s[2] for s in statuses if s[1] is None]
    if rule.operator == "absent" and result is not None:
        result = not result

    patient_value = "; ".join(reasons)
    if result is not None:
        return RuleOutcome(result, patient_value, expected, "deterministic",
                           f"Patient record: {patient_value}.", [], "condition")

    notes = ["Requires clinical confirmation; an undocumented condition is never treated as absent."]
    joined = "; ".join(reasons)
    explanation = (
        f"{joined[:1].upper() + joined[1:]}. Requires clinical confirmation: the system does not treat an "
        "undocumented condition as absent and does not infer a diagnosis from laboratory values."
    )
    related = _related_lab_summary(criterion, profile)
    if related and criterion.normalized_rule and criterion.normalized_rule.attribute == "condition":
        labs = " or ".join(label(a) for a, _ in related)
        values = "; ".join(v for _, v in related)
        name = terms[0]
        explanation += (
            f" The protocol gives no numeric definition, so {name} is not confirmed by {labs} alone "
            f"(patient {values})."
        )
        notes.append(f"{name[:1].upper() + name[1:]} is not confirmed by {labs} alone.")
    nlp_notes = _possible_matches(terms, profile, matcher)
    if nlp_notes:
        explanation += " A clinical language model flagged possibly related records for review (see notes)."
        notes.extend(nlp_notes)
    return RuleOutcome(None, patient_value, expected, "not_evaluable", explanation, notes, "condition")


def _evaluate_event(criterion: Criterion, profile: NormalizedProfile) -> RuleOutcome:
    rule = criterion.normalized_rule
    assert rule is not None
    subject = rule.attribute.split(":", 1)[1]
    days = int(float(rule.value))  # type: ignore[arg-type]
    expected = f"{subject} within {days} days"
    candidates = []
    for med in profile.medications:
        if condition_matches(subject, med.name) or normalize_text(med.name) in normalize_text(subject):
            candidates.append((med.name, med.stop_date or med.start_date))
    for dx in profile.diagnoses:
        if condition_matches(subject, dx.name):
            candidates.append((dx.name, dx.documented_at))
    if not candidates:
        return RuleOutcome(None, None, expected, "not_evaluable",
                           f"No record of {subject}; absence cannot be assumed. Requires clinical confirmation.",
                           ["Event not documented."], rule.attribute)
    for name, when in candidates:
        hit = within_days(when, profile.as_of, days)
        if hit is True:
            return RuleOutcome(True, f"{name} on {when}", expected, "deterministic",
                               f"{name} recorded on {when}, within {days} days of {profile.as_of}.", [], rule.attribute)
    if any(when is None for _, when in candidates):
        return RuleOutcome(None, ", ".join(n for n, _ in candidates), expected, "not_evaluable",
                           f"{subject} is documented without a date; the time window cannot be checked.",
                           ["Undated event."], rule.attribute)
    name, when = candidates[0]
    return RuleOutcome(False, f"{name} on {when}", expected, "deterministic",
                       f"Most relevant record of {subject} ({when}) is outside the {days}-day window.", [],
                       rule.attribute)


def _evaluate_data_completeness(criterion: Criterion, profile: NormalizedProfile) -> RuleOutcome:
    """A protocol criterion about the data itself ("missing or stale required laboratory result").

    It is never decided against the patient: incomplete data makes it UNKNOWN (more information
    required), and complete, current data rules it out.
    """
    rule = criterion.normalized_rule
    assert rule is not None
    attrs = rule.value if isinstance(rule.value, list) else []
    expected = "all required results present, current and unambiguous"
    if not attrs:
        return RuleOutcome(None, None, expected, "not_evaluable",
                           "The protocol does not name which results are required; requires review by the study team.",
                           ["Required results not specified."], "data_completeness")
    problems, fine = [], []
    for attr in attrs:
        av = profile.attributes.get(attr)
        if av is None or av.status == "missing" or av.value is None:
            problems.append(f"{label(attr)} missing")
        elif av.status != "ok":
            problems.append(f"{label(attr)} {av.status}")
        else:
            fine.append(label(attr))
    if problems:
        summary = "; ".join(problems)
        return RuleOutcome(None, summary, expected, "deterministic",
                           f"Required data are incomplete ({summary}); eligibility cannot be assumed.",
                           [f"Incomplete data: {summary}."], "data_completeness")
    # Complete data satisfies an inclusion-style check and rules out an exclusion-style one.
    return RuleOutcome(criterion.category == "inclusion", "all present and current", expected, "deterministic",
                       f"All required results are present and current ({', '.join(fine)}).", [], "data_completeness")


def _semantic_payload(criterion: Criterion, profile: NormalizedProfile) -> dict:
    """The minimum patient data a free-text criterion can need (data minimisation for the LLM call):
    age, sex, conditions, medications and history, plus labs only from the criterion's clinical domains."""
    domain_labs = {a for d in domains_for(criterion.original_text) for a in domain_attributes(d)}
    age = profile.attributes.get("age")
    return {
        "as_of": profile.as_of.isoformat(),
        "age": age.value if age else None,
        "sex": profile.sex,
        "diagnoses": [d.model_dump(mode="json") for d in profile.diagnoses],
        "medications": [m.model_dump(mode="json") for m in profile.medications],
        "history": [h.model_dump(mode="json") for h in profile.history],
        "labs": {a: {"value": v.value, "unit": v.unit, "observed_at": v.observed_at, "status": v.status}
                 for a, v in profile.attributes.items() if a in domain_labs and v.value is not None},
    }


def _evaluate_semantic(criterion: Criterion, profile: NormalizedProfile, llm: LLMClient | None) -> RuleOutcome:
    expected = criterion.original_text
    if llm is None:
        return RuleOutcome(None, None, expected, "not_evaluable",
                           "This criterion has no machine-readable rule and no semantic model is configured; "
                           "it requires review by the study team.",
                           ["Not evaluable without clinical review."])
    system = (
        "You decide whether a patient meets one clinical trial criterion. " + UNTRUSTED_DATA_RULE + " "
        "Answer 'yes' or 'no' only if the patient data states it explicitly; otherwise answer 'unknown'."
    )
    user = (
        f"<document type=\"criterion\">{criterion.original_text}</document>\n"
        f"<document type=\"patient\">{json.dumps(_semantic_payload(criterion, profile), default=str)}</document>\n"
        "Does the patient meet the criterion as written?"
    )
    try:
        answer = _SemanticAnswer.model_validate(llm.complete_json(system, user, SEMANTIC_SCHEMA))
    except (LLMError, ValidationError, ValueError, TypeError) as exc:
        log.warning("semantic evaluation failed for %s: %s", criterion.criterion_id, exc)
        return RuleOutcome(None, None, expected, "not_evaluable",
                           "Semantic evaluation did not return a valid structured answer; treated as UNKNOWN.",
                           [f"Semantic model output rejected: {type(exc).__name__}."])
    result = {"yes": True, "no": False, "unknown": None}[answer.answer]
    return RuleOutcome(result, None, expected, "semantic_llm", answer.explanation,
                       ["Semantic model judgement; requires human confirmation."])


_NUMERIC_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "between"}


def _combine(op: str, a: bool | None, b: bool | None) -> bool | None:
    """Three-valued (Kleene) and/or: an unknown clause never makes the whole criterion pass or fail
    unless the other clause alone decides it."""
    if op == "and":
        if a is False or b is False:
            return False
        return True if a is True and b is True else None
    if a is True or b is True:
        return True
    return False if a is False and b is False else None


def _evaluate_compound(criterion: Criterion, profile: NormalizedProfile) -> RuleOutcome:
    first, second = criterion.normalized_rule, criterion.secondary_rule
    assert first is not None and second is not None and criterion.rule_combinator is not None
    op = criterion.rule_combinator
    outcomes = [_evaluate_numeric(r, profile) if r.operator in _NUMERIC_OPERATORS else
                RuleOutcome(None, None, describe(r), "not_evaluable", f"Clause {describe(r)} is not supported.",
                            ["Unsupported rule shape."], r.attribute)
                for r in (first, second)]
    a, b = outcomes
    result = _combine(op, a.result, b.result)
    # The attribute shown is the one that decided the outcome, or the one still unknown.
    if result is None:
        decider = a if a.result is None else b
    elif op == "and":
        decider = (a if a.result is False else b) if result is False else a
    else:
        decider = (a if a.result is True else b) if result is True else a
    values = [f"{label(o.attribute or '')} {o.patient_value}" for o in outcomes if o.patient_value]
    method = "deterministic" if all(o.method == "deterministic" for o in outcomes) or result is not None \
        else "not_evaluable"
    notes = [n for o in outcomes for n in o.notes]
    if result is None:
        notes.append(f"Compound criterion ({op}): one clause could not be decided, so the criterion is UNKNOWN.")
    return RuleOutcome(
        result=result,
        patient_value="; ".join(values) or None,
        expected=f"{a.expected} {op} {b.expected}",
        method=method,  # type: ignore[arg-type]
        explanation=f"Both clauses joined by '{op}': (1) {a.explanation} (2) {b.explanation}",
        notes=notes,
        attribute=decider.attribute,
    )


def evaluate_criterion(criterion: Criterion, profile: NormalizedProfile, llm: LLMClient | None = None,
                       concept_matcher: ConceptMatcher | None = None) -> RuleOutcome:
    rule = criterion.normalized_rule
    if rule is not None and criterion.secondary_rule is not None:
        return _evaluate_compound(criterion, profile)
    if rule is None:
        return _evaluate_semantic(criterion, profile, llm)
    if rule.attribute == "data_completeness":
        return _evaluate_data_completeness(criterion, profile)
    if rule.attribute == "condition" and rule.operator in {"present", "absent"}:
        return _evaluate_condition(criterion, profile, concept_matcher)
    if rule.operator == "within_days" and rule.attribute.startswith("event:"):
        return _evaluate_event(criterion, profile)
    if rule.operator in _NUMERIC_OPERATORS:
        return _evaluate_numeric(rule, profile)
    return RuleOutcome(None, None, describe(rule), "not_evaluable",
                       f"Operator {rule.operator} on {rule.attribute} is not supported deterministically.",
                       ["Unsupported rule shape."], rule.attribute)
