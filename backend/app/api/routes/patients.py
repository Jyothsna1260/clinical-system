from fastapi import APIRouter, Depends

from app.agents.patient_profile import normalize_patient
from app.api.errors import not_found
from app.config import get_settings
from app.schemas.api import PatientCreate, PatientOut, PatientSummary, PatientUpdate
from app.schemas.clinical import PatientProfileInput
from app.security.deps import get_current_user
from app.services import audit
from app.storage import PatientRecord, PatientVersion, Store, UserRecord, get_store

router = APIRouter(prefix="/api/patients", tags=["patients"])


def owned_patient(store: Store, patient_id: str, user: UserRecord) -> PatientRecord:
    patient = store.patients.get_owned(patient_id, user.id)
    if patient is None or not patient.versions:
        raise not_found("Patient")
    return patient


def _out(patient: PatientRecord) -> PatientOut:
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


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(body: PatientCreate, user: UserRecord = Depends(get_current_user),
                   store: Store = Depends(get_store)) -> PatientOut:
    patient = store.patients.put(PatientRecord(owner_id=user.id, versions=[_version(1, body.label, body.profile)]))
    audit.record(store, user.id, "patient.created", "patient", patient.id, {"version": 1})
    return _out(patient)


@router.get("", response_model=list[PatientSummary])
def list_patients(user: UserRecord = Depends(get_current_user),
                  store: Store = Depends(get_store)) -> list[PatientSummary]:
    patients = [p for p in store.patients.for_owner(user.id) if p.versions]
    patients.sort(key=lambda p: p.latest.created_at, reverse=True)
    return [PatientSummary(id=p.id, label=p.latest.label, version=p.latest.version, updated_at=p.latest.created_at)
            for p in patients]


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, user: UserRecord = Depends(get_current_user),
                store: Store = Depends(get_store)) -> PatientOut:
    patient = owned_patient(store, patient_id, user)
    audit.record(store, user.id, "patient.read", "patient", patient_id)
    return _out(patient)


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: str, body: PatientUpdate, user: UserRecord = Depends(get_current_user),
                   store: Store = Depends(get_store)) -> PatientOut:
    owned_patient(store, patient_id, user)

    def add_version(patient: PatientRecord) -> None:
        latest = patient.latest
        patient.versions = [*patient.versions, _version(latest.version + 1, body.label or latest.label, body.profile)]

    patient = store.patients.update(patient_id, add_version)
    audit.record(store, user.id, "patient.updated", "patient", patient_id, {"version": patient.latest.version})
    return _out(patient)
