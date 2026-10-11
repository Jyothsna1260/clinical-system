"""Typed shared state for the eligibility LangGraph workflow."""

import operator
from typing import Annotated, Any, TypedDict

from app.agents.contradiction import ContradictionReport
from app.schemas.clinical import (
    Criterion,
    CriterionEvaluation,
    EligibilityResult,
    EvidenceReference,
    ExternalReference,
    NormalizedProfile,
    PatientProfileInput,
)

NODE_ORDER = [
    "validate_inputs",
    "extract_protocol",
    "normalize_patient",
    "retrieve_evidence",
    "inclusion_matching",
    "exclusion_detection",
    "detect_contradictions",
    "web_research",
    "review_and_decide",
    "persist",
]


def keep_first(a: Any, b: Any) -> Any:
    """Reducer: the first error recorded wins (parallel branches may both fail)."""
    return a if a else b


class WorkflowError(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


class EligibilityState(TypedDict, total=False):
    # inputs
    run_id: str
    trial_id: str
    document_id: str
    protocol_version: str
    pages: list[dict[str, Any]]
    patient_input: dict[str, Any]
    criteria: list[Criterion]
    # intermediate
    patient: PatientProfileInput
    profile: NormalizedProfile
    evidence: dict[str, list[EvidenceReference]]
    inclusion_results: list[CriterionEvaluation]
    exclusion_results: list[CriterionEvaluation]
    contradictions: ContradictionReport
    extraction_method: str
    extraction_warnings: list[str]
    external_references: list[ExternalReference]
    research_warnings: list[str]
    # outputs
    result: EligibilityResult
    error: Annotated[WorkflowError | None, keep_first]
    logs: Annotated[list[dict[str, Any]], operator.add]
