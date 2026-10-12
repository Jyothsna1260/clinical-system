"""Core clinical schemas shared by the agents, the workflow and the API.

These models are strict: every agent output is validated against them before it is
saved or returned.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Operator = Literal["gt", "gte", "lt", "lte", "eq", "between", "present", "absent", "within_days"]
Category = Literal["inclusion", "exclusion"]
InclusionStatus = Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]
ExclusionStatus = Literal["TRIGGERED", "NOT_TRIGGERED", "UNKNOWN"]
ComparisonMethod = Literal["deterministic", "semantic_llm", "not_evaluable"]
OverallStatus = Literal["ELIGIBLE", "NOT_ELIGIBLE", "MORE_INFORMATION_REQUIRED"]

INCLUSION_STATUSES = {"SATISFIED", "UNSATISFIED", "UNKNOWN"}
EXCLUSION_STATUSES = {"TRIGGERED", "NOT_TRIGGERED", "UNKNOWN"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- protocol


class NormalizedRule(StrictModel):
    """Machine-readable form of a criterion.

    `attribute` is a canonical patient attribute such as ``age`` or ``egfr`` for
    numeric rules, or ``condition`` for diagnosis/history rules, in which case
    ``value`` holds the list of condition terms (any of which matches).
    """

    attribute: str
    operator: Operator
    value: float | str | list[str] | None = None
    value_max: float | None = None
    unit: str | None = None
    inclusive: bool | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "NormalizedRule":
        if self.operator == "between" and (self.value is None or self.value_max is None):
            raise ValueError("between requires value and value_max")
        if self.operator in {"gt", "gte", "lt", "lte", "within_days"} and not isinstance(self.value, (int, float)):
            raise ValueError(f"{self.operator} requires a numeric value")
        return self


class Criterion(StrictModel):
    criterion_id: str = Field(pattern=r"^(INC|EXC)-\d{2,3}$")
    trial_id: str
    category: Category
    original_text: str = Field(min_length=1)
    normalized_rule: NormalizedRule | None = None
    # Compound criteria ("creatinine > 1.5 mg/dL or CrCl < 40 mL/min", "eGFR >= 30 and <= 90"):
    # the second clause and how it combines with the first. Absent for single-clause criteria.
    secondary_rule: NormalizedRule | None = None
    rule_combinator: Literal["and", "or"] | None = None
    required_attributes: list[str] = Field(default_factory=list)
    source_page: int = Field(ge=1)
    source_excerpt: str = Field(min_length=1)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    extraction_method: Literal["rule_based", "llm"] = "rule_based"

    @model_validator(mode="after")
    def _prefix_matches_category(self) -> "Criterion":
        expected = "INC" if self.category == "inclusion" else "EXC"
        if not self.criterion_id.startswith(expected):
            raise ValueError(f"{self.criterion_id} does not match category {self.category}")
        if (self.secondary_rule is None) != (self.rule_combinator is None):
            raise ValueError("secondary_rule and rule_combinator must be set together")
        if self.secondary_rule is not None and self.normalized_rule is None:
            raise ValueError("secondary_rule requires normalized_rule")
        return self


# --------------------------------------------------------------------------- patient


class Demographics(StrictModel):
    age: float | None = Field(default=None, ge=0, le=130)
    sex: Literal["male", "female", "other", "unknown"] | None = None
    date_of_birth: date | None = None


class LabInput(StrictModel):
    name: str = Field(min_length=1)
    value: float
    unit: str | None = None
    observed_at: date | None = None
    reference_range: str | None = None


class DiagnosisInput(StrictModel):
    name: str = Field(min_length=1)
    code: str | None = None
    documented_at: date | None = None


class MedicationInput(StrictModel):
    name: str = Field(min_length=1)
    start_date: date | None = None
    stop_date: date | None = None


class HistoryInput(StrictModel):
    condition: str = Field(min_length=1)
    present: bool | None = None


class PatientProfileInput(StrictModel):
    """Structured patient profile. `as_of` fixes the reference date for staleness checks."""

    demographics: Demographics = Field(default_factory=Demographics)
    labs: list[LabInput] = Field(default_factory=list)
    diagnoses: list[DiagnosisInput] = Field(default_factory=list)
    medications: list[MedicationInput] = Field(default_factory=list)
    history: list[HistoryInput] = Field(default_factory=list)
    as_of: date | None = None


class DataQualityFlag(StrictModel):
    attribute: str
    flag: Literal["missing", "stale", "conflicting", "ambiguous", "unit_unconvertible"]
    detail: str


class NormalizedObservation(StrictModel):
    attribute: str
    source_name: str
    value: float
    unit: str | None
    original_value: float
    original_unit: str | None
    observed_at: date | None = None


class AttributeValue(StrictModel):
    """The resolved value the matching agents use for one attribute."""

    attribute: str
    value: float | None
    unit: str | None
    observed_at: date | None = None
    status: Literal["ok", "missing", "stale", "conflicting", "ambiguous"]
    detail: str | None = None
    observations: list[NormalizedObservation] = Field(default_factory=list)


class NormalizedProfile(StrictModel):
    as_of: date
    sex: str | None
    attributes: dict[str, AttributeValue]
    diagnoses: list[DiagnosisInput]
    medications: list[MedicationInput]
    history: list[HistoryInput]
    data_quality_flags: list[DataQualityFlag] = Field(default_factory=list)


# --------------------------------------------------------------------------- results


class EvidenceReference(StrictModel):
    page: int = Field(ge=1)
    excerpt: str = Field(min_length=1)
    chunk_id: str | None = None
    source: Literal["protocol_citation", "retrieval"] = "protocol_citation"
    score: float | None = None


class CriterionEvaluation(StrictModel):
    criterion_id: str
    category: Category
    status: str
    original_text: str
    patient_value: str | None = None
    expected_condition: str
    comparison_method: ComparisonMethod
    explanation: str
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    attribute: str | None = None

    @model_validator(mode="after")
    def _status_matches_category(self) -> "CriterionEvaluation":
        allowed = INCLUSION_STATUSES if self.category == "inclusion" else EXCLUSION_STATUSES
        if self.status not in allowed:
            raise ValueError(f"status {self.status} is not valid for {self.category} criteria")
        return self


class PatientFinding(StrictModel):
    attribute: str
    value: str
    observed_at: date | None = None


class SilentExclusionTrigger(StrictModel):
    trigger_id: str
    domain: str
    inclusion_criterion_ids: list[str]
    exclusion_criterion_ids: list[str]
    related_failing_criterion_ids: list[str]
    patient_findings: list[PatientFinding] = Field(min_length=1)
    explanation: str
    evidence_references: list[EvidenceReference] = Field(min_length=1)
    review_priority: Literal["high", "medium", "low"]
    confidence: float = Field(ge=0.0, le=1.0)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    requires_human_review: Literal[True] = True


class Conflict(StrictModel):
    conflict_type: Literal["conflicting_rules", "inconsistent_patient_values", "ambiguous_rule"]
    description: str
    criterion_ids: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)


class MissingInformation(StrictModel):
    attribute: str
    criterion_ids: list[str]
    reason: str


class DecisiveEvidence(StrictModel):
    criterion_id: str
    status: str
    patient_value: str | None
    expected_condition: str
    evidence_references: list[EvidenceReference]


class PatientValueUsed(StrictModel):
    """A patient value the agents compared against the protocol, with its normalization trace."""

    attribute: str
    label: str
    value: str
    observed_at: date | None = None
    status: str = "ok"
    source: str | None = None  # e.g. "Creatinine 132.6 umol/L (converted)"
    criterion_ids: list[str] = Field(default_factory=list)


class ExternalReference(StrictModel):
    """Web search context for an ambiguous criterion. Shown to the reviewer; never used in the decision."""

    criterion_id: str
    query: str
    title: str
    url: str
    snippet: str = ""
    provider: str


class PriorAssessment(StrictModel):
    """Persistent agent memory: the previous assessment of the same patient for the same trial."""

    run_id: str
    overall_status: str | None
    analyzed_at: datetime | None = None
    patient_profile_version: int
    protocol_version: str
    changed_criteria: list[str] = Field(default_factory=list)


class EligibilityResult(StrictModel):
    run_id: str
    overall_status: OverallStatus
    inclusion_results: list[CriterionEvaluation]
    exclusion_results: list[CriterionEvaluation]
    silent_exclusion_triggers: list[SilentExclusionTrigger]
    missing_information: list[MissingInformation]
    unresolved_conflicts: list[Conflict]
    decisive_evidence: list[DecisiveEvidence]
    final_explanation: str
    human_review_required: Literal[True] = True
    human_review_notice: str
    protocol_version: str
    analyzed_at: datetime
    reviewer_notes: list[str] = Field(default_factory=list)
    patient_values_used: list[PatientValueUsed] = Field(default_factory=list)
    external_references: list[ExternalReference] = Field(default_factory=list)
    prior_assessment: PriorAssessment | None = None

    @field_validator("inclusion_results")
    @classmethod
    def _inclusion_only(cls, v: list[CriterionEvaluation]) -> list[CriterionEvaluation]:
        if any(e.category != "inclusion" for e in v):
            raise ValueError("inclusion_results may only hold inclusion evaluations")
        return v

    @field_validator("exclusion_results")
    @classmethod
    def _exclusion_only(cls, v: list[CriterionEvaluation]) -> list[CriterionEvaluation]:
        if any(e.category != "exclusion" for e in v):
            raise ValueError("exclusion_results may only hold exclusion evaluations")
        return v
