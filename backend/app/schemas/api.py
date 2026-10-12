"""Request/response models for the HTTP API."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.clinical import Criterion, DataQualityFlag, EligibilityResult, PatientProfileInput


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str | None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TrialSummary(BaseModel):
    id: str
    title: str
    status: str
    index_status: str
    current_version: int
    protocol_version: str | None
    page_count: int | None
    criteria_count: int
    created_at: datetime


class TrialDetail(TrialSummary):
    filename: str | None
    extraction_method: str | None
    extraction_warnings: list[str] = []
    criteria: list[Criterion]
    error: dict | None = None


class PageOut(BaseModel):
    trial_id: str
    page: int
    page_count: int
    text: str


class PatientCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    profile: PatientProfileInput


class PatientUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    profile: PatientProfileInput


class PatientOut(BaseModel):
    id: str
    profile_version_id: str
    version: int
    label: str
    profile: PatientProfileInput
    data_quality_flags: list[DataQualityFlag]
    versions: list[int]
    created_at: datetime
    updated_at: datetime


class PatientSummary(BaseModel):
    id: str
    label: str
    version: int
    updated_at: datetime


class AnalyzeRequest(BaseModel):
    trial_id: str
    patient_id: str


class RunCreated(BaseModel):
    run_id: str
    status: str


class NodeProgress(BaseModel):
    node: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    summary: dict[str, Any] | None = None


class RunStatus(BaseModel):
    run_id: str
    status: str
    overall_status: str | None
    progress: list[NodeProgress]
    error: dict | None
    created_at: datetime
    completed_at: datetime | None


class RunSummary(BaseModel):
    run_id: str
    trial_id: str
    trial_title: str
    patient_id: str
    patient_label: str
    patient_profile_version: int
    status: str
    overall_status: str | None
    created_at: datetime


class RunDetail(BaseModel):
    run_id: str
    status: str
    trial_id: str
    trial_title: str
    patient_id: str
    patient_label: str
    patient_profile_version: int
    protocol_version: str
    # Typed for the API schema; a stored result from an older version that no longer validates is
    # returned as saved (dict) rather than failing the request.
    result: Annotated[EligibilityResult | dict, Field(union_mode="left_to_right")] | None
    error: dict | None
    human_review_notice: str
    created_at: datetime
    completed_at: datetime | None


class EvidenceItem(BaseModel):
    criterion_id: str
    page: int
    excerpt: str
    chunk_id: str | None = None
    source: str | None = None
    score: float | None = None


class RunEvidence(BaseModel):
    run_id: str
    trial_id: str
    protocol_version: str
    evidence: list[EvidenceItem]
    human_review_notice: str


class AuditEventOut(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str | None
    details: dict[str, Any]
    created_at: str


class AgentExecutionLog(BaseModel):
    node: str
    status: str
    started_at: str | None
    ended_at: str | None
    summary: dict[str, Any] | None


class RunAudit(BaseModel):
    run_id: str
    audit_events: list[AuditEventOut]
    agent_execution_logs: list[AgentExecutionLog]
