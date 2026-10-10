"""Background eligibility analysis: wires the LangGraph workflow to the file store."""

import logging
from datetime import datetime

from app.config import get_settings
from app.services import audit
from app.services.llm import get_llm
from app.services.trials import get_or_build_index, load_criteria
from app.storage import AgentLog, RunRecord, Store, get_store, utcnow
from app.workflow.graph import run_eligibility
from app.workflow.state import EligibilityState

log = logging.getLogger(__name__)


def make_reporter(store: Store, run_id: str):
    """Record per-node progress on the run. Parallel graph branches call this concurrently."""

    def report(node: str, status: str, started_at: datetime | None, ended_at: datetime | None,
               summary: dict | None) -> None:
        def apply(run: RunRecord) -> None:
            entry = run.agent_logs.get(node) or AgentLog(node=node, status=status)
            entry.status = status
            if started_at is not None:
                entry.started_at = started_at
            entry.ended_at = ended_at
            entry.summary = summary
            run.agent_logs = {**run.agent_logs, node: entry}

        store.runs.update(run_id, apply)

    return report


def persist_state(store: Store, run_id: str, state: EligibilityState) -> RunRecord | None:
    """Write run outputs. Idempotent by run_id: a retry overwrites the previous outcome."""
    result = state.get("result")
    error = state.get("error")

    def apply(run: RunRecord) -> None:
        if result is not None and not error:
            run.status = "completed"
            run.overall_status = result.overall_status
            run.result = result.model_dump(mode="json")
            run.error = None
        else:
            run.status = "failed"
            run.overall_status = None
            run.result = None
            run.error = dict(error) if error else {
                "code": "UNKNOWN_ERROR", "message": "Analysis did not produce a result.", "details": {}}
        run.completed_at = utcnow()

    run = store.runs.update(run_id, apply)
    if run is not None:
        audit.record(store, run.owner_id, "analysis.completed" if run.status == "completed" else "analysis.failed",
                     "eligibility_run", run.id, {"overall_status": run.overall_status, "error": run.error})
    return run


def run_analysis(run_id: str) -> None:
    """Entry point for FastAPI BackgroundTasks. Safe to retry: persistence is idempotent."""
    settings = get_settings()
    store = get_store()
    run = store.runs.update(run_id, lambda r: setattr(r, "status", "running"))
    if run is None:
        log.error("run %s not found", run_id)
        return
    try:
        doc = store.documents.get(run.document_id)
        patient = store.patients.get(run.patient_id)
        profile = patient.version(run.patient_profile_version) if patient else None

        def index_provider(pages):
            return get_or_build_index(run.trial_id, doc.id, pages) if doc else None

        run_eligibility(
            run_id=run.id,
            trial_id=run.trial_id,
            document_id=run.document_id,
            protocol_version=run.protocol_version,
            pages=doc.pages if doc else [],
            patient_input=profile.data if profile else {},
            criteria=load_criteria(doc),
            llm=get_llm(settings),
            index_provider=index_provider,
            reporter=make_reporter(store, run.id),
            persister=lambda state: persist_state(store, run.id, state),
            stale_days=settings.stale_days,
        )
    except Exception as exc:
        log.exception("analysis %s crashed", run_id)

        def fail(r: RunRecord) -> None:
            r.status = "failed"
            r.error = {"code": "ANALYSIS_CRASHED", "message": str(exc), "details": {}}
            r.completed_at = utcnow()

        store.runs.update(run_id, fail)
