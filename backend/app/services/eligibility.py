"""Use cases for eligibility runs: start one, then read its progress, result, evidence and audit trail.

The analysis itself runs in the background (``app.services.analysis.run_analysis``).
"""

from app.config import HUMAN_REVIEW_NOTICE
from app.errors import AppError, not_found
from app.schemas.api import NodeProgress, RunDetail, RunStatus, RunSummary
from app.services import audit
from app.services.patients import require_patient
from app.services.trials import latest_document, require_trial
from app.state import get_run_state
from app.storage import AgentLog, RunRecord, Store
from app.workflow.state import NODE_ORDER


def require_run(store: Store, run_id: str, owner_id: str) -> RunRecord:
    run = store.runs.get_owned(run_id, owner_id)
    if run is None:
        raise not_found("Run")
    return run


def start_analysis(store: Store, owner_id: str, trial_id: str, patient_id: str) -> RunRecord:
    """Create a queued run pinned to the current protocol version and the latest patient profile version."""
    trial = require_trial(store, trial_id, owner_id)
    if trial.status != "ready":
        raise AppError(409, "TRIAL_NOT_READY", f"Trial is not ready for analysis (status: {trial.status}).",
                       trial.error or {})
    doc = latest_document(store, trial)
    if doc is None:
        raise AppError(409, "TRIAL_NOT_READY", "Trial has no protocol document.")
    profile = require_patient(store, patient_id, owner_id).latest
    run = store.runs.put(RunRecord(
        owner_id=owner_id, trial_id=trial.id, document_id=doc.id, protocol_version=doc.protocol_version,
        patient_id=patient_id, patient_profile_id=profile.id, patient_profile_version=profile.version,
    ))
    audit.record(store, owner_id, "analysis.requested", "eligibility_run", run.id,
                 {"trial_id": trial.id, "patient_id": patient_id, "patient_version": profile.version})
    return run


def _labels(store: Store, run: RunRecord) -> tuple[str, str]:
    """Trial title, and the patient label as it was at the analysed profile version."""
    trial = store.trials.get(run.trial_id)
    patient = store.patients.get(run.patient_id)
    version = patient.version(run.patient_profile_version) if patient else None
    return (trial.title if trial else "", version.label if version else "")


def list_runs(store: Store, owner_id: str, limit: int) -> list[RunSummary]:
    runs = sorted(store.runs.for_owner(owner_id), key=lambda r: r.created_at, reverse=True)[:limit]
    out = []
    for r in runs:
        title, label = _labels(store, r)
        out.append(RunSummary(
            run_id=r.id, trial_id=r.trial_id, trial_title=title, patient_id=r.patient_id, patient_label=label,
            patient_profile_version=r.patient_profile_version, status=r.status,
            overall_status=r.overall_status, created_at=r.created_at,
        ))
    return out


def run_status(store: Store, run_id: str, owner_id: str) -> RunStatus:
    """Per-agent progress: the durable agent logs, overlaid with the live workflow state while it exists."""
    run = require_run(store, run_id, owner_id)
    live = {name: AgentLog(node=name, status=e.get("status", "unknown"), started_at=e.get("started_at"),
                           ended_at=e.get("ended_at"), summary=e.get("summary"))
            for name, e in get_run_state().nodes(run.id).items()}
    logs = {**run.agent_logs, **live}
    nodes = NODE_ORDER + [n for n in logs if n not in NODE_ORDER]
    progress = []
    for name in nodes:
        entry = logs.get(name)
        progress.append(
            NodeProgress(node=name, status="pending") if entry is None
            else NodeProgress(node=name, status=entry.status, started_at=entry.started_at,
                              ended_at=entry.ended_at, summary=entry.summary)
        )
    return RunStatus(run_id=run.id, status=run.status, overall_status=run.overall_status, progress=progress,
                     error=run.error, created_at=run.created_at, completed_at=run.completed_at)


def run_detail(store: Store, run_id: str, owner_id: str) -> RunDetail:
    run = require_run(store, run_id, owner_id)
    title, label = _labels(store, run)
    audit.record(store, owner_id, "result.read", "eligibility_run", run.id)
    return RunDetail(
        run_id=run.id, status=run.status, trial_id=run.trial_id, trial_title=title,
        patient_id=run.patient_id, patient_label=label,
        patient_profile_version=run.patient_profile_version, protocol_version=run.protocol_version,
        result=run.result, error=run.error, human_review_notice=HUMAN_REVIEW_NOTICE,
        created_at=run.created_at, completed_at=run.completed_at,
    )


def run_evidence(store: Store, run_id: str, owner_id: str) -> dict:
    """Every protocol citation behind the run's criterion decisions, ordered by criterion and page."""
    run = require_run(store, run_id, owner_id)
    audit.record(store, owner_id, "evidence.read", "eligibility_run", run.id)
    evaluations = (run.result or {}).get("inclusion_results", []) + (run.result or {}).get("exclusion_results", [])
    evidence = sorted(
        ({"criterion_id": e["criterion_id"], "page": ref["page"], "excerpt": ref["excerpt"],
          "chunk_id": ref.get("chunk_id"), "source": ref.get("source"), "score": ref.get("score")}
         for e in evaluations for ref in e.get("evidence_references", [])),
        key=lambda r: (r["criterion_id"], r["page"]),
    )
    return {"run_id": run.id, "trial_id": run.trial_id, "protocol_version": run.protocol_version,
            "evidence": evidence, "human_review_notice": HUMAN_REVIEW_NOTICE}


def run_audit(store: Store, run_id: str, owner_id: str) -> dict:
    """Audit events for the run, its trial and its patient, plus the per-agent execution log."""
    run = require_run(store, run_id, owner_id)
    related = {run.id, run.trial_id, run.patient_id}
    events = sorted((e for e in store.audit.for_owner(owner_id) if e.resource_id in related),
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
