"""Agent C - Inclusion Matching.

Deterministic comparators for numeric, range and date rules; the LLM is used only for
non-numeric semantic rules and its output must validate or the result is UNKNOWN.
SATISFIED / UNSATISFIED / UNKNOWN per inclusion criterion.
"""

from app.engine.rule_evaluator import evaluate_criterion
from app.nlp.clinical import ConceptMatcher
from app.schemas.clinical import Criterion, CriterionEvaluation, EvidenceReference, NormalizedProfile
from app.services.llm import LLMClient

_STATUS = {True: "SATISFIED", False: "UNSATISFIED", None: "UNKNOWN"}


def match_inclusion(
    criteria: list[Criterion],
    profile: NormalizedProfile,
    evidence: dict[str, list[EvidenceReference]],
    llm: LLMClient | None = None,
    concept_matcher: ConceptMatcher | None = None,
) -> list[CriterionEvaluation]:
    results = []
    for c in criteria:
        if c.category != "inclusion":
            continue
        outcome = evaluate_criterion(c, profile, llm, concept_matcher)
        status = _STATUS[outcome.result]
        notes = list(outcome.notes) + list(c.review_reasons)
        results.append(
            CriterionEvaluation(
                criterion_id=c.criterion_id,
                category="inclusion",
                status=status,
                original_text=c.original_text,
                patient_value=outcome.patient_value,
                expected_condition=outcome.expected,
                comparison_method=outcome.method,
                explanation=outcome.explanation,
                evidence_references=evidence.get(c.criterion_id, []),
                uncertainty_notes=notes,
                requires_human_review=status == "UNKNOWN" or outcome.method == "semantic_llm",
                attribute=outcome.attribute,
            )
        )
    return results
