from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.schemas.api import AnalyzeRequest, RunAudit, RunCreated, RunDetail, RunEvidence, RunStatus, RunSummary
from app.security.deps import get_current_user
from app.services import eligibility
from app.services.analysis import run_analysis
from app.storage import Store, UserRecord, get_store

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


@router.post("/analyze", response_model=RunCreated, status_code=202)
def analyze(body: AnalyzeRequest, background: BackgroundTasks, user: UserRecord = Depends(get_current_user),
            store: Store = Depends(get_store)) -> RunCreated:
    run = eligibility.start_analysis(store, user.id, body.trial_id, body.patient_id)
    background.add_task(run_analysis, run.id)
    return RunCreated(run_id=run.id, status=run.status)


@router.get("", response_model=list[RunSummary])
def list_runs(limit: int = Query(default=20, ge=1, le=100), user: UserRecord = Depends(get_current_user),
              store: Store = Depends(get_store)) -> list[RunSummary]:
    return eligibility.list_runs(store, user.id, limit)


@router.get("/{run_id}/status", response_model=RunStatus)
def run_status(run_id: str, user: UserRecord = Depends(get_current_user),
               store: Store = Depends(get_store)) -> RunStatus:
    return eligibility.run_status(store, run_id, user.id)


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> RunDetail:
    return eligibility.run_detail(store, run_id, user.id)


@router.get("/{run_id}/evidence", response_model=RunEvidence)
def get_evidence(run_id: str, user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> dict:
    return eligibility.run_evidence(store, run_id, user.id)


@router.get("/{run_id}/audit", response_model=RunAudit)
def get_audit(run_id: str, user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> dict:
    return eligibility.run_audit(store, run_id, user.id)
