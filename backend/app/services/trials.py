"""Use cases for trial protocols.

Upload flow::

    validate bytes -> parse PDF pages -> Agent A extracts criteria -> save trial + document
    -> (background) chunk pages and build the retrieval index
"""

import hashlib
import logging
from pathlib import Path

from app.agents.protocol_extraction import extract_criteria
from app.config import get_settings
from app.errors import AppError, not_found
from app.rag.chunker import chunk_pages
from app.rag.index import build_index, load_index
from app.rag.pdf_loader import PageText, PDFReadError, is_pdf_bytes, load_pdf_bytes, pages_from_dicts
from app.schemas.api import PageOut, TrialDetail, TrialSummary
from app.schemas.clinical import Criterion
from app.services import audit
from app.services.llm import get_llm
from app.storage import ProtocolDocumentRecord, Store, TrialRecord, get_store

log = logging.getLogger(__name__)


# ---- lookups -------------------------------------------------------------------------------

def require_trial(store: Store, trial_id: str, owner_id: str) -> TrialRecord:
    trial = store.trials.get_owned(trial_id, owner_id)
    if trial is None:
        raise not_found("Trial")
    return trial


def latest_document(store: Store, trial: TrialRecord) -> ProtocolDocumentRecord | None:
    return next((d for d in store.documents.where(trial_id=trial.id) if d.version == trial.current_version), None)


def load_criteria(doc: ProtocolDocumentRecord | None) -> list[Criterion]:
    return [Criterion.model_validate(c) for c in doc.criteria] if doc else []


# ---- responses -----------------------------------------------------------------------------

def _summary_fields(trial: TrialRecord, doc: ProtocolDocumentRecord | None) -> dict:
    return dict(
        id=trial.id, title=trial.title, status=trial.status, index_status=trial.index_status,
        current_version=trial.current_version, protocol_version=doc.protocol_version if doc else None,
        page_count=doc.page_count if doc else None, criteria_count=len(doc.criteria) if doc else 0,
        created_at=trial.created_at,
    )


def trial_detail(store: Store, trial: TrialRecord) -> TrialDetail:
    doc = latest_document(store, trial)
    return TrialDetail(
        **_summary_fields(trial, doc),
        filename=doc.filename if doc else None,
        extraction_method=doc.extraction_method if doc else None,
        extraction_warnings=doc.extraction_warnings if doc else [],
        criteria=load_criteria(doc),
        error=trial.error,
    )


def list_trials(store: Store, owner_id: str) -> list[TrialSummary]:
    trials = sorted(store.trials.for_owner(owner_id), key=lambda t: t.created_at, reverse=True)
    return [TrialSummary(**_summary_fields(t, latest_document(store, t))) for t in trials]


def get_page(store: Store, trial_id: str, owner_id: str, page: int) -> PageOut:
    trial = require_trial(store, trial_id, owner_id)
    doc = latest_document(store, trial)
    if doc is None or page < 1 or page > doc.page_count:
        raise not_found("Page")
    text = next((p["text"] for p in doc.pages if int(p["page"]) == page), "")
    return PageOut(trial_id=trial.id, page=page, page_count=doc.page_count, text=text)


# ---- upload --------------------------------------------------------------------------------

def max_upload_bytes() -> int:
    return get_settings().max_upload_mb * 1024 * 1024


def _validate_upload(filename: str | None, content_type: str | None, data: bytes) -> None:
    if len(data) > max_upload_bytes():
        raise AppError(413, "FILE_TOO_LARGE", f"Protocol PDF must be at most {get_settings().max_upload_mb} MB.")
    if not data:
        raise AppError(400, "EMPTY_FILE", "Uploaded file is empty.")
    if not is_pdf_bytes(data):
        raise AppError(400, "INVALID_FILE_TYPE", "Only PDF protocol documents are accepted.",
                       {"filename": filename, "content_type": content_type})


def upload_protocol(
    store: Store, owner_id: str, filename: str | None, content_type: str | None, title: str | None, data: bytes
) -> tuple[TrialRecord, ProtocolDocumentRecord]:
    """Validate, parse and store a protocol PDF with its extracted criteria."""
    _validate_upload(filename, content_type, data)
    name = (filename or "protocol.pdf")[:300]
    try:
        pages = load_pdf_bytes(data)
    except PDFReadError as exc:
        raise AppError(400, "UNREADABLE_PDF", str(exc), {"filename": filename}) from exc

    trial = TrialRecord(owner_id=owner_id, title=(title or name.rsplit(".", 1)[0])[:300])
    doc = _store_document(trial, name, data, pages)
    if doc.criteria:
        trial.status = "ready"
    else:
        trial.status = "error"
        trial.error = {"code": "NO_CRITERIA", "message": "No inclusion or exclusion criteria were found in the protocol."}

    store.trials.put(trial)  # the trial first: in PostgreSQL the document references it
    store.documents.put(doc)
    audit.record(store, owner_id, "trial.uploaded", "trial", trial.id,
                 {"filename": name, "sha256": doc.sha256, "pages": doc.page_count})
    return trial, doc


def _store_document(trial: TrialRecord, filename: str, data: bytes, pages: list[PageText]) -> ProtocolDocumentRecord:
    """Save the PDF to disk and run Agent A (protocol extraction) over its pages."""
    sha = hashlib.sha256(data).hexdigest()
    path = get_settings().uploads_dir / trial.id / "v1.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    result = extract_criteria(pages, trial.id, get_llm())
    criteria = sorted(result.criteria, key=lambda c: (c.category != "inclusion", c.criterion_id))
    return ProtocolDocumentRecord(
        trial_id=trial.id, owner_id=trial.owner_id, version=1, protocol_version=f"v1-{sha[:12]}",
        filename=filename, file_path=str(path), sha256=sha, page_count=len(pages),
        pages=[p.to_dict() for p in pages],
        criteria=[c.model_dump(mode="json") for c in criteria],
        extraction_method=criteria[0].extraction_method if criteria else None,
        extraction_warnings=result.warnings,
    )


# ---- retrieval index -----------------------------------------------------------------------

def index_dir(trial_id: str, document_id: str) -> Path:
    return get_settings().index_dir / trial_id / document_id


def get_or_build_index(trial_id: str, document_id: str, pages: list[PageText]):
    s = get_settings()
    directory = index_dir(trial_id, document_id)
    idx = load_index(directory, s.embeddings_enabled, s.embedding_model)
    if idx is None:
        idx = build_index(chunk_pages(pages, trial_id, document_id), directory, s.embeddings_enabled, s.embedding_model)
    return idx


def build_index_task(trial_id: str, document_id: str) -> None:
    """Background task: build and persist the per-trial retrieval index."""
    store = get_store()
    doc = store.documents.get(document_id)
    if doc is None or store.trials.update(trial_id, lambda t: setattr(t, "index_status", "building")) is None:
        return
    try:
        idx = get_or_build_index(trial_id, document_id, pages_from_dicts(doc.pages))
        status, error = f"ready:{getattr(idx, 'kind', 'unknown')}", None
    except Exception as exc:
        log.exception("index build failed for trial %s", trial_id)
        status, error = "error", {"code": "INDEX_FAILED", "message": str(exc)}

    def finish(trial: TrialRecord) -> None:
        trial.index_status = status
        if error:
            trial.error = error

    store.trials.update(trial_id, finish)
