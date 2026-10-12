"""LangGraph orchestration of the six agents.

validate_inputs -> extract_protocol -> normalize_patient -> retrieve_evidence
  -> [inclusion_matching || exclusion_detection] -> detect_contradictions
  -> web_research -> review_and_decide -> persist -> END

Invalid/unreadable input or zero extracted criteria routes to `handle_error`, which
returns a structured error and still goes through `persist` so the run is recorded.
Runtime dependencies (LLM client, index provider, clinical NLP matcher, web search client,
prior-assessment memory, progress reporter, persister) are passed via `config["configurable"]` so the
graph itself stays pure and testable.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache, wraps
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.contradiction import detect_contradictions
from app.agents.exclusion_detection import detect_exclusions
from app.agents.inclusion_matching import match_inclusion
from app.agents.patient_profile import normalize_patient
from app.agents.protocol_extraction import excerpt_on_page, extract_criteria
from app.agents.reviewer import compare_with_prior, patient_values_used, review_and_decide
from app.agents.web_research import research_ambiguous_criteria
from app.rag.chunker import chunk_pages
from app.rag.index import KeywordIndex
from app.rag.pdf_loader import pages_from_dicts
from app.rag.retriever import retrieve_evidence
from app.schemas.clinical import PatientProfileInput
from app.workflow.state import EligibilityState

log = logging.getLogger(__name__)

Reporter = Callable[[str, str, datetime | None, datetime | None, dict | None], None]


class NodeFailure(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def _cfg(config: dict | None, key: str, default: Any = None) -> Any:
    return ((config or {}).get("configurable") or {}).get(key, default)


def _safe_reporter(reporter: Reporter | None) -> Reporter | None:
    """Wrap the progress reporter so a progress-store error is logged instead of stopping the run."""
    if reporter is None:
        return None

    def report(*args) -> None:
        try:
            reporter(*args)
        except Exception:
            log.exception("progress reporting failed for node %s", args[0] if args else "?")

    return report


def node(name: str, always: bool = False):
    """Wrap a node: skip after an error, report progress, log timing, convert failures."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(state: EligibilityState, config: RunnableConfig | None = None) -> dict:
            if state.get("error") and not always:
                return {}
            reporter: Reporter | None = _safe_reporter(_cfg(config, "reporter"))
            started = datetime.now(UTC)
            t0 = time.perf_counter()
            if reporter:
                reporter(name, "running", started, None, None)
            try:
                update, summary = fn(state, config)
                status = "completed"
            except NodeFailure as exc:
                update = {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
                summary, status = {"error": exc.message}, "failed"
            except Exception as exc:  # unexpected failure: structured error, never a crash
                log.exception("node %s failed", name)
                update = {"error": {"code": "AGENT_FAILURE", "message": f"The {name} step failed unexpectedly.",
                                    "details": {"node": name, "error_type": type(exc).__name__}}}
                summary, status = {"error": str(exc)}, "failed"
            ended = datetime.now(UTC)
            summary = {**summary, "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}
            if reporter:
                reporter(name, status, started, ended, summary)
            entry = {"node": name, "status": status, "started_at": started.isoformat(),
                     "ended_at": ended.isoformat(), "summary": summary}
            return {**update, "logs": [entry]}

        return wrapper

    return decorator


@node("validate_inputs")
def validate_inputs(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    pages = state.get("pages") or []
    if not pages or not any(str(p.get("text", "")).strip() for p in pages):
        raise NodeFailure("UNREADABLE_PROTOCOL", "Protocol has no extractable text.", {"page_count": len(pages)})
    try:
        patient = PatientProfileInput.model_validate(state.get("patient_input") or {})
    except ValidationError as exc:
        raise NodeFailure("INVALID_PATIENT_PROFILE", "Patient profile failed validation.",
                          {"errors": exc.errors(include_url=False, include_context=False)}) from exc
    return {"patient": patient}, {"pages": len(pages), "labs": len(patient.labs), "diagnoses": len(patient.diagnoses)}


@node("extract_protocol")
def extract_protocol(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    pages = pages_from_dicts(state["pages"])
    criteria = state.get("criteria")
    method, warnings = "stored", []
    if not criteria:
        result = extract_criteria(pages, state["trial_id"], _cfg(config, "llm"))
        criteria, method, warnings = result.criteria, result.method, result.warnings
    else:
        # Re-verify stored criteria against the stored page text; never trust stale citations.
        by_no = {p.page: p.text for p in pages}
        verified = []
        for c in criteria:
            if not excerpt_on_page(c.source_excerpt, by_no.get(c.source_page, "")) and not c.requires_human_review:
                c = c.model_copy(update={
                    "requires_human_review": True,
                    "extraction_confidence": min(c.extraction_confidence, 0.3),
                    "review_reasons": c.review_reasons + [f"Source excerpt not found on page {c.source_page}."],
                })
            verified.append(c)
        criteria = verified
    if not criteria:
        raise NodeFailure("NO_CRITERIA", "No inclusion or exclusion criteria could be extracted from the protocol.",
                          {"pages": len(pages)})
    inc = sum(c.category == "inclusion" for c in criteria)
    return (
        {"criteria": criteria, "extraction_method": method, "extraction_warnings": warnings},
        {"criteria": len(criteria), "inclusion": inc, "exclusion": len(criteria) - inc, "method": method,
         "flagged_for_review": sum(c.requires_human_review for c in criteria)},
    )


@node("normalize_patient")
def normalize_patient_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    required = sorted({a for c in state["criteria"] for a in c.required_attributes})
    profile = normalize_patient(state["patient"], required, stale_days=_cfg(config, "stale_days", 90))
    flags = [f"{f.attribute}:{f.flag}" for f in profile.data_quality_flags]
    return {"profile": profile}, {"attributes": len(profile.attributes), "data_quality_flags": flags}


@node("retrieve_evidence")
def retrieve_evidence_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    pages = pages_from_dicts(state["pages"])
    provider = _cfg(config, "index_provider")
    index = provider(pages) if provider else None
    if index is None:
        index = KeywordIndex(chunk_pages(pages, state["trial_id"], state.get("document_id", "doc")))
    evidence = retrieve_evidence(state["criteria"], index, {p.page: p.text for p in pages})
    total = sum(len(v) for v in evidence.values())
    uncited = [cid for cid, refs in evidence.items() if not refs]
    return {"evidence": evidence}, {"index": getattr(index, "kind", "unknown"), "references": total, "uncited": uncited}


def _semantic_llm(config: dict | None):
    """The LLM for semantic (free-text) criteria, or None when LLM_SEMANTIC_EVALUATION is off, in which
    case patient data is never sent to the model and such criteria are UNKNOWN (clinical review)."""
    return _cfg(config, "llm") if _cfg(config, "semantic_evaluation", True) else None


def _status_counts(evals) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in evals:
        counts[e.status] = counts.get(e.status, 0) + 1
    return counts


@node("inclusion_matching")
def inclusion_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    results = match_inclusion(state["criteria"], state["profile"], state["evidence"], _semantic_llm(config),
                              _cfg(config, "concept_matcher"))
    return {"inclusion_results": results}, _status_counts(results)


@node("exclusion_detection")
def exclusion_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    results = detect_exclusions(state["criteria"], state["profile"], state["evidence"], _semantic_llm(config),
                                _cfg(config, "concept_matcher"))
    return {"exclusion_results": results}, _status_counts(results)


@node("detect_contradictions")
def contradictions_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    report = detect_contradictions(state["criteria"], state["inclusion_results"], state["exclusion_results"],
                                   state["profile"])
    return {"contradictions": report}, {
        "silent_exclusion_triggers": len(report.triggers),
        "conflicts": len(report.conflicts),
        "missing_information": len(report.missing_information),
    }


@node("web_research")
def web_research_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    client = _cfg(config, "web_search")
    refs, warnings = research_ambiguous_criteria(
        state["criteria"], state["inclusion_results"] + state["exclusion_results"], client,
        _cfg(config, "web_search_max_queries", 3),
    )
    return {"external_references": refs, "research_warnings": warnings}, {
        "enabled": client is not None,
        "provider": getattr(client, "provider", None),
        "references": len(refs),
        "criteria": sorted({r.criterion_id for r in refs}),
    }


@node("review_and_decide")
def review_node(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    result = review_and_decide(
        run_id=state["run_id"],
        protocol_version=state.get("protocol_version", "unversioned"),
        inclusion_results=state["inclusion_results"],
        exclusion_results=state["exclusion_results"],
        report=state["contradictions"],
    )
    evaluations = result.inclusion_results + result.exclusion_results
    memory, memory_notes = compare_with_prior(_cfg(config, "prior_assessment"), result.overall_status, evaluations)
    result = result.model_copy(update={
        "patient_values_used": patient_values_used(state["profile"], evaluations),
        "external_references": state.get("external_references") or [],
        "prior_assessment": memory,
        "reviewer_notes": result.reviewer_notes + memory_notes + (state.get("research_warnings") or []),
    })
    return {"result": result}, {"overall_status": result.overall_status, "decisive": len(result.decisive_evidence),
                                "compared_with_prior": memory is not None}


@node("handle_error", always=True)
def handle_error(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    err = state.get("error") or {"code": "UNKNOWN_ERROR", "message": "Unknown workflow error", "details": {}}
    return {}, {"error_code": err["code"]}


@node("persist", always=True)
def persist(state: EligibilityState, config: RunnableConfig | None) -> tuple[dict, dict]:
    persister = _cfg(config, "persister")
    if persister is None:
        return {}, {"persisted": False}
    persister(state)
    return {}, {"persisted": True}


def _after(next_node: str):
    def route(state: EligibilityState) -> str:
        return "handle_error" if state.get("error") else next_node

    return route


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(EligibilityState)
    g.add_node("validate_inputs", validate_inputs)
    g.add_node("extract_protocol", extract_protocol)
    g.add_node("normalize_patient", normalize_patient_node)
    g.add_node("retrieve_evidence", retrieve_evidence_node)
    g.add_node("inclusion_matching", inclusion_node)
    g.add_node("exclusion_detection", exclusion_node)
    g.add_node("detect_contradictions", contradictions_node)
    g.add_node("web_research", web_research_node)
    g.add_node("review_and_decide", review_node)
    g.add_node("handle_error", handle_error)
    g.add_node("persist", persist)

    g.add_edge(START, "validate_inputs")
    g.add_conditional_edges("validate_inputs", _after("extract_protocol"), ["extract_protocol", "handle_error"])
    g.add_conditional_edges("extract_protocol", _after("normalize_patient"), ["normalize_patient", "handle_error"])
    g.add_conditional_edges("normalize_patient", _after("retrieve_evidence"), ["retrieve_evidence", "handle_error"])
    g.add_edge("retrieve_evidence", "inclusion_matching")
    g.add_edge("retrieve_evidence", "exclusion_detection")
    g.add_edge(["inclusion_matching", "exclusion_detection"], "detect_contradictions")
    g.add_conditional_edges("detect_contradictions", _after("web_research"), ["web_research", "handle_error"])
    g.add_conditional_edges("web_research", _after("review_and_decide"), ["review_and_decide", "handle_error"])
    g.add_conditional_edges("review_and_decide", _after("persist"), ["persist", "handle_error"])
    g.add_edge("handle_error", "persist")
    g.add_edge("persist", END)
    return g.compile()


def run_eligibility(
    *,
    run_id: str,
    trial_id: str,
    pages: list[dict],
    patient_input: dict,
    document_id: str = "doc",
    protocol_version: str = "unversioned",
    criteria: list | None = None,
    llm=None,
    index_provider=None,
    reporter: Reporter | None = None,
    persister=None,
    stale_days: int = 90,
    concept_matcher=None,
    web_search=None,
    web_search_max_queries: int = 3,
    prior_assessment: dict | None = None,
    semantic_evaluation: bool = True,
) -> EligibilityState:
    state: EligibilityState = {
        "run_id": run_id,
        "trial_id": trial_id,
        "document_id": document_id,
        "protocol_version": protocol_version,
        "pages": pages,
        "patient_input": patient_input,
        "logs": [],
        "error": None,
    }
    if criteria:
        state["criteria"] = criteria
    config = {"configurable": {
        "llm": llm, "index_provider": index_provider, "reporter": reporter,
        "persister": persister, "stale_days": stale_days, "concept_matcher": concept_matcher,
        "web_search": web_search, "web_search_max_queries": web_search_max_queries,
        "prior_assessment": prior_assessment, "semantic_evaluation": semantic_evaluation,
    }}
    return build_graph().invoke(state, config=config)
