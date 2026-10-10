from fastapi import APIRouter, Depends

from app.schemas.api import PatientCreate, PatientOut, PatientSummary, PatientUpdate
from app.security.deps import get_current_user
from app.services import patients
from app.storage import Store, UserRecord, get_store

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(body: PatientCreate, user: UserRecord = Depends(get_current_user),
                   store: Store = Depends(get_store)) -> PatientOut:
    return patients.create_patient(store, user.id, body.label, body.profile)


@router.get("", response_model=list[PatientSummary])
def list_patients(user: UserRecord = Depends(get_current_user),
                  store: Store = Depends(get_store)) -> list[PatientSummary]:
    return patients.list_patients(store, user.id)


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, user: UserRecord = Depends(get_current_user),
                store: Store = Depends(get_store)) -> PatientOut:
    return patients.read_patient(store, patient_id, user.id)


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: str, body: PatientUpdate, user: UserRecord = Depends(get_current_user),
                   store: Store = Depends(get_store)) -> PatientOut:
    return patients.update_patient(store, patient_id, user.id, body.label, body.profile)
