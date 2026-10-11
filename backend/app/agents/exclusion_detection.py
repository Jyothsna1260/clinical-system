"""Agent D - Exclusion Detection.

Same comparators as inclusion matching. Diagnosis-only exclusions (for example "severe
renal impairment" with no numeric definition) are TRIGGERED only when the diagnosis is
documented, NOT_TRIGGERED only when it is explicitly documented absent, and otherwise
UNKNOWN with "requires clinical confirmation". A diagnosis is never inferred from a
single lab value unless the protocol defines it that way.
"""

from app.engine.rule_evaluator import evaluate_criterion
from app.nlp.clinical import ConceptMatcher
from app.schemas.clinical import Criterion, CriterionEvaluation, EvidenceReference, NormalizedProfile
from app.services.llm import LLMClient

_STATUS = {True: "TRIGGERED", False: "NOT_TRIGGERED", None: "UNKNOWN"}


def detect_exclusions(
    criteria: list[Criterion],
    profile: NormalizedProfile,
    evidence: dict[str, list[EvidenceReference]],
    llm: LLMClient | None = None,
    concept_matcher: ConceptMatcher | None = None,
) -> list[CriterionEvaluation]:
    results = []
    for c in criteria:
        if c.category != "exclusion":
            continue
        outcome = evaluate_criterion(c, profile, llm, concept_matcher)
        status = _STATUS[outcome.result]
        notes = list(outcome.notes) + list(c.review_reasons)
        results.append(
            CriterionEvaluation(
                criterion_id=c.criterion_id,
                category="exclusion",
                status=status,
                original_text=c.original_text,
                patient_value=outcome.patient_value,
                expected_condition=outcome.expected,
                comparison_method=outcome.method,
                explanation=outcome.explanation,
                evidence_references=evidence.get(c.criterion_id, []),
                uncertainty_notes=notes,
                requires_human_review=status != "NOT_TRIGGERED" or outcome.method == "semantic_llm",
                attribute=outcome.attribute,
            )
        )
    return results
