from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.errors import AppError, not_found
from app.api.routes.patients import owned_patient
from app.api.routes.trials import owned_trial
from app.config import HUMAN_REVIEW_NOTICE
from app.schemas.api import AnalyzeRequest, NodeProgress, RunCreated, RunDetail, RunStatus, RunSummary
from app.security.deps import get_current_user
from app.services import audit
from app.services.analysis import run_analysis
from app.services.trials import latest_document
from app.storage import RunRecord, Store, UserRecord, get_store
from app.workflow.state import NODE_ORDER

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


def owned_run(store: Store, run_id: str, user: UserRecord) -> RunRecord:
    run = store.runs.get_owned(run_id, user.id)
    if run is None:
        raise not_found("Run")
    return run


def _labels(store: Store, run: RunRecord) -> tuple[str, str]:
    """Trial title and the patient label as it was at the analysed profile version."""
    trial = store.trials.get(run.trial_id)
    patient = store.patients.get(run.patient_id)
    version = patient.version(run.patient_profile_version) if patient else None
    return (trial.title if trial else "", version.label if version else "")


def _evidence(run: RunRecord) -> list[dict]:
    if not run.result:
        return []
    evaluations = run.result.get("inclusion_results", []) + run.result.get("exclusion_results", [])
    rows = [
        {"criterion_id": e["criterion_id"], "page": ref["page"], "excerpt": ref["excerpt"],
         "chunk_id": ref.get("chunk_id"), "source": ref.get("source"), "score": ref.get("score")}
        for e in evaluations for ref in e.get("evidence_references", [])
    ]
    return sorted(rows, key=lambda r: (r["criterion_id"], r["page"]))


@router.post("/analyze", response_model=RunCreated, status_code=202)
def analyze(body: AnalyzeRequest, background: BackgroundTasks, user: UserRecord = Depends(get_current_user),
            store: Store = Depends(get_store)) -> RunCreated:
    trial = owned_trial(store, body.trial_id, user)
    if trial.status != "ready":
        raise AppError(409, "TRIAL_NOT_READY", f"Trial is not ready for analysis (status: {trial.status}).",
                       trial.error or {})
    doc = latest_document(store, trial)
    if doc is None:
        raise AppError(409, "TRIAL_NOT_READY", "Trial has no protocol document.")
    profile = owned_patient(store, body.patient_id, user).latest
    run = store.runs.put(RunRecord(
        owner_id=user.id, trial_id=trial.id, document_id=doc.id, protocol_version=doc.protocol_version,
        patient_id=body.patient_id, patient_profile_id=profile.id, patient_profile_version=profile.version,
    ))
    audit.record(store, user.id, "analysis.requested", "eligibility_run", run.id,
                 {"trial_id": trial.id, "patient_id": run.patient_id, "patient_version": profile.version})
    background.add_task(run_analysis, run.id)
    return RunCreated(run_id=run.id, status=run.status)


@router.get("", response_model=list[RunSummary])
def list_runs(limit: int = Query(default=20, ge=1, le=100), user: UserRecord = Depends(get_current_user),
              store: Store = Depends(get_store)) -> list[RunSummary]:
    runs = sorted(store.runs.for_owner(user.id), key=lambda r: r.created_at, reverse=True)[:limit]
    out = []
    for r in runs:
        title, label = _labels(store, r)
        out.append(RunSummary(
            run_id=r.id, trial_id=r.trial_id, trial_title=title, patient_id=r.patient_id, patient_label=label,
            patient_profile_version=r.patient_profile_version, status=r.status,
            overall_status=r.overall_status, created_at=r.created_at,
        ))
    return out


@router.get("/{run_id}/status", response_model=RunStatus)
def run_status(run_id: str, user: UserRecord = Depends(get_current_user),
               store: Store = Depends(get_store)) -> RunStatus:
    run = owned_run(store, run_id, user)
    nodes = NODE_ORDER + [n for n in run.agent_logs if n not in NODE_ORDER]
    progress = [
        NodeProgress(node=n, status="pending") if (entry := run.agent_logs.get(n)) is None
        else NodeProgress(node=n, status=entry.status, started_at=entry.started_at, ended_at=entry.ended_at,
                          summary=entry.summary)
        for n in nodes
    ]
    return RunStatus(run_id=run.id, status=run.status, overall_status=run.overall_status, progress=progress,
                     error=run.error, created_at=run.created_at, completed_at=run.completed_at)


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> RunDetail:
    run = owned_run(store, run_id, user)
    title, label = _labels(store, run)
    audit.record(store, user.id, "result.read", "eligibility_run", run.id)
    return RunDetail(
        run_id=run.id, status=run.status, trial_id=run.trial_id, trial_title=title,
        patient_id=run.patient_id, patient_label=label,
        patient_profile_version=run.patient_profile_version, protocol_version=run.protocol_version,
        result=run.result, error=run.error, human_review_notice=HUMAN_REVIEW_NOTICE,
        created_at=run.created_at, completed_at=run.completed_at,
    )


@router.get("/{run_id}/evidence")
def get_evidence(run_id: str, user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> dict:
    run = owned_run(store, run_id, user)
    audit.record(store, user.id, "evidence.read", "eligibility_run", run.id)
    return {
        "run_id": run.id,
        "trial_id": run.trial_id,
        "protocol_version": run.protocol_version,
        "evidence": _evidence(run),
        "human_review_notice": HUMAN_REVIEW_NOTICE,
    }


@router.get("/{run_id}/audit")
def get_audit(run_id: str, user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> dict:
    run = owned_run(store, run_id, user)
    related = {run.id, run.trial_id, run.patient_id}
    events = sorted((e for e in store.audit.for_owner(user.id) if e.resource_id in related),
                    key=lambda e: e.created_at)
    logs = sorted(run.agent_logs.values(), key=lambda entry: (entry.started_at is None, entry.started_at))
    return {
        "run_id": run.id,
        "audit_events": [
            {"id": e.id, "action": e.action, "resource_type": e.resource_type, "resource_id": e.resource_id,
             "details": e.details, "created_at": e.created_at.isoformat()}
            for e in events
        ],
        "agent_execution_logs": [
            {"node": entry.node, "status": entry.status,
             "started_at": entry.started_at.isoformat() if entry.started_at else None,
             "ended_at": entry.ended_at.isoformat() if entry.ended_at else None, "summary": entry.summary}
            for entry in logs
        ],
    }
