"""Protocol ingestion: store the PDF, extract criteria (Agent A) and build the retrieval index."""

import hashlib
import logging
from pathlib import Path

from app.agents.protocol_extraction import extract_criteria
from app.config import get_settings
from app.rag.chunker import chunk_pages
from app.rag.index import build_index, load_index
from app.rag.pdf_loader import PageText, load_pdf_bytes, pages_from_dicts
from app.schemas.clinical import Criterion
from app.services.llm import get_llm
from app.storage import ProtocolDocumentRecord, Store, TrialRecord, get_store

log = logging.getLogger(__name__)


def index_dir(trial_id: str, document_id: str) -> Path:
    return get_settings().index_dir / trial_id / document_id


def create_trial_from_pdf(
    store: Store, owner_id: str, title: str, filename: str, data: bytes
) -> tuple[TrialRecord, ProtocolDocumentRecord]:
    """Parse, persist and extract. Raises PDFReadError for unreadable files (nothing is stored)."""
    pages = load_pdf_bytes(data)
    sha = hashlib.sha256(data).hexdigest()

    trial = TrialRecord(owner_id=owner_id, title=title)
    path = get_settings().uploads_dir / trial.id / "v1.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    result = extract_criteria(pages, trial.id, get_llm())
    criteria = sorted(result.criteria, key=lambda c: (c.category != "inclusion", c.criterion_id))
    doc = ProtocolDocumentRecord(
        trial_id=trial.id, owner_id=owner_id, version=1, protocol_version=f"v1-{sha[:12]}",
        filename=filename, file_path=str(path), sha256=sha, page_count=len(pages),
        pages=[p.to_dict() for p in pages],
        criteria=[c.model_dump(mode="json") for c in criteria],
        extraction_method=criteria[0].extraction_method if criteria else None,
        extraction_warnings=result.warnings,
    )
    if criteria:
        trial.status = "ready"
    else:
        trial.status = "error"
        trial.error = {"code": "NO_CRITERIA", "message": "No inclusion or exclusion criteria were found in the protocol."}

    store.documents.put(doc)
    store.trials.put(trial)
    return trial, doc


def latest_document(store: Store, trial: TrialRecord) -> ProtocolDocumentRecord | None:
    return store.documents.first(lambda d: d.trial_id == trial.id and d.version == trial.current_version)


def load_criteria(doc: ProtocolDocumentRecord | None) -> list[Criterion]:
    return [Criterion.model_validate(c) for c in doc.criteria] if doc else []


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
