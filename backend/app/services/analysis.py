"""Background eligibility analysis: wires the LangGraph workflow to storage and workflow state.

Live per-agent progress goes to the run-state backend (Redis or memory, ``app.state``); outputs and
the final agent logs go to the durable run record (PostgreSQL or the file store).
"""

import logging
from datetime import datetime, timedelta

from app.config import get_settings
from app.nlp import get_concept_matcher
from app.services import audit
from app.services.llm import get_llm
from app.services.trials import get_or_build_index, load_criteria
from app.services.web_search import get_web_search
from app.state import RunState, get_run_state
from app.storage import AgentLog, RunRecord, Store, get_store, utcnow
from app.workflow.graph import run_eligibility
from app.workflow.state import EligibilityState

log = logging.getLogger(__name__)


def make_reporter(run_state: RunState, run_id: str):
    """Record per-node progress in the run state. Parallel graph branches call this concurrently."""

    def report(node: str, status: str, started_at: datetime | None, ended_at: datetime | None,
               summary: dict | None) -> None:
        previous = run_state.nodes(run_id).get(node) or {}
        run_state.record_node(run_id, node, {
            "status": status,
            "started_at": started_at or previous.get("started_at"),
            "ended_at": ended_at,
            "summary": summary,
        })

    return report


def sync_agent_logs(store: Store, run_state: RunState, run_id: str) -> None:
    """Copy the live per-agent state into the durable run record."""
    nodes = run_state.nodes(run_id)
    if not nodes:
        return

    def apply(run: RunRecord) -> None:
        run.agent_logs = {**run.agent_logs, **{
            name: AgentLog(node=name, status=e.get("status", "unknown"), started_at=e.get("started_at"),
                           ended_at=e.get("ended_at"), summary=e.get("summary"))
            for name, e in nodes.items()
        }}

    store.runs.update(run_id, apply)


def prior_assessment(store: Store, run: RunRecord) -> dict | None:
    """Persistent memory: the latest earlier completed assessment of the same patient for the same trial."""
    earlier = [r for r in store.runs.where(trial_id=run.trial_id, patient_id=run.patient_id)
               if r.id != run.id and r.owner_id == run.owner_id and r.status == "completed" and r.result
               and r.created_at <= run.created_at]
    if not earlier:
        return None
    prev = max(earlier, key=lambda r: r.created_at)
    statuses = {e["criterion_id"]: e["status"]
                for e in prev.result.get("inclusion_results", []) + prev.result.get("exclusion_results", [])}
    return {"run_id": prev.id, "overall_status": prev.overall_status, "analyzed_at": prev.result.get("analyzed_at"),
            "patient_profile_version": prev.patient_profile_version,
            "protocol_version": prev.protocol_version, "criterion_statuses": statuses}


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
    run_state = get_run_state()
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
            reporter=make_reporter(run_state, run.id),
            persister=lambda state: persist_state(store, run.id, state),
            stale_days=settings.stale_days,
            concept_matcher=get_concept_matcher(settings),
            web_search=get_web_search(settings),
            web_search_max_queries=settings.web_search_max_queries,
            prior_assessment=prior_assessment(store, run),
            semantic_evaluation=settings.llm_semantic_evaluation,
        )
        sync_agent_logs(store, run_state, run.id)
    except Exception as exc:
        log.exception("analysis %s crashed", run_id)
        _fail_if_unfinished(store, run_id, "ANALYSIS_CRASHED",
                            "The analysis stopped because of an internal error. Please try again.",
                            {"error_type": type(exc).__name__})
        sync_agent_logs(store, run_state, run_id)
        return
    # The workflow returned but never saved an outcome (e.g. saving the result itself failed).
    _fail_if_unfinished(store, run_id, "ANALYSIS_INCOMPLETE",
                        "The analysis finished without saving a result. Please try again.", {})


def _fail_if_unfinished(store: Store, run_id: str, code: str, message: str, details: dict) -> None:
    """Mark a run failed unless it already reached a final status."""

    def fail(r: RunRecord) -> None:
        if r.status in {"completed", "failed"}:
            return
        r.status = "failed"
        r.error = {"code": code, "message": message, "details": details}
        r.completed_at = utcnow()

    store.runs.update(run_id, fail)


def fail_interrupted_runs(store: Store, older_than_minutes: int) -> int:
    """Startup recovery: runs left queued/running by a restart can never finish (background tasks are
    in-process), so mark them failed and let the user re-run them. Returns how many were marked."""
    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    stuck = [r for status in ("queued", "running") for r in store.runs.where(status=status)
             if r.updated_at < cutoff]
    for r in stuck:
        _fail_if_unfinished(store, r.id, "ANALYSIS_INTERRUPTED",
                            "The analysis was interrupted (the service restarted). Please run it again.", {})
        audit.record(store, r.owner_id, "analysis.failed", "eligibility_run", r.id, {"error": "ANALYSIS_INTERRUPTED"})
    return len(stuck)
