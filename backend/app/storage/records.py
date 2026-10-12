"""Persisted record types. Each record is stored as one JSON document on local disk."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Record(BaseModel):
    """Base for every stored document: UUID id plus created/updated timestamps."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class OwnedRecord(Record):
    owner_id: str


class UserRecord(Record):
    email: str
    hashed_password: str
    full_name: str | None = None


class TrialRecord(OwnedRecord):
    title: str
    status: str = "processing"  # processing | ready | error
    index_status: str = "pending"  # pending | building | ready:<kind> | error
    current_version: int = 1
    error: dict[str, Any] | None = None  # upload / extraction failure
    index_error: dict[str, Any] | None = None  # retrieval-index build failure (internal; keyword index is used)


class ProtocolDocumentRecord(OwnedRecord):
    """One uploaded protocol version, with its page text and extracted criteria."""

    trial_id: str
    version: int
    protocol_version: str
    filename: str
    file_path: str
    sha256: str
    page_count: int
    pages: list[dict[str, Any]]
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    extraction_method: str | None = None
    extraction_warnings: list[str] = Field(default_factory=list)


class PatientVersion(BaseModel):
    id: str = Field(default_factory=new_id)
    version: int
    label: str
    data: dict[str, Any]
    created_at: datetime = Field(default_factory=utcnow)


class PatientRecord(OwnedRecord):
    """A patient and the full history of their profile versions (oldest first)."""

    versions: list[PatientVersion] = Field(default_factory=list)

    @property
    def latest(self) -> PatientVersion:
        return self.versions[-1]

    def version(self, number: int) -> PatientVersion | None:
        return next((v for v in self.versions if v.version == number), None)


class AgentLog(BaseModel):
    node: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    summary: dict[str, Any] | None = None


class RunRecord(OwnedRecord):
    trial_id: str
    document_id: str
    protocol_version: str
    patient_id: str
    patient_profile_id: str
    patient_profile_version: int
    status: str = "queued"  # queued | running | completed | failed
    overall_status: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    agent_logs: dict[str, AgentLog] = Field(default_factory=dict)
    completed_at: datetime | None = None


class AuditEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    owner_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
