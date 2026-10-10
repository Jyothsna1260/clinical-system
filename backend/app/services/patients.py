"""Use cases for patient profiles. Every edit appends a new version; nothing is overwritten."""

from app.agents.patient_profile import normalize_patient
from app.config import get_settings
from app.errors import not_found
from app.schemas.api import PatientOut, PatientSummary
from app.schemas.clinical import PatientProfileInput
from app.services import audit
from app.storage import PatientRecord, PatientVersion, Store


def require_patient(store: Store, patient_id: str, owner_id: str) -> PatientRecord:
    patient = store.patients.get_owned(patient_id, owner_id)
    if patient is None or not patient.versions:
        raise not_found("Patient")
    return patient


def patient_out(patient: PatientRecord) -> PatientOut:
    latest = patient.latest
    profile = PatientProfileInput.model_validate(latest.data)
    normalized = normalize_patient(profile, ["age"], stale_days=get_settings().stale_days)
    return PatientOut(
        id=patient.id, profile_version_id=latest.id, version=latest.version, label=latest.label,
        profile=profile, data_quality_flags=normalized.data_quality_flags,
        versions=[v.version for v in patient.versions],
        created_at=patient.created_at, updated_at=latest.created_at,
    )


def _version(number: int, label: str, profile: PatientProfileInput) -> PatientVersion:
    return PatientVersion(version=number, label=label, data=profile.model_dump(mode="json"))


def create_patient(store: Store, owner_id: str, label: str, profile: PatientProfileInput) -> PatientOut:
    patient = store.patients.put(PatientRecord(owner_id=owner_id, versions=[_version(1, label, profile)]))
    audit.record(store, owner_id, "patient.created", "patient", patient.id, {"version": 1})
    return patient_out(patient)


def update_patient(store: Store, patient_id: str, owner_id: str, label: str | None,
                   profile: PatientProfileInput) -> PatientOut:
    require_patient(store, patient_id, owner_id)

    def add_version(patient: PatientRecord) -> None:
        latest = patient.latest
        patient.versions = [*patient.versions, _version(latest.version + 1, label or latest.label, profile)]

    patient = store.patients.update(patient_id, add_version)
    audit.record(store, owner_id, "patient.updated", "patient", patient_id, {"version": patient.latest.version})
    return patient_out(patient)


def read_patient(store: Store, patient_id: str, owner_id: str) -> PatientOut:
    patient = require_patient(store, patient_id, owner_id)
    audit.record(store, owner_id, "patient.read", "patient", patient_id)
    return patient_out(patient)


def list_patients(store: Store, owner_id: str) -> list[PatientSummary]:
    patients = [p for p in store.patients.for_owner(owner_id) if p.versions]
    patients.sort(key=lambda p: p.latest.created_at, reverse=True)
    return [PatientSummary(id=p.id, label=p.latest.label, version=p.latest.version, updated_at=p.latest.created_at)
            for p in patients]
