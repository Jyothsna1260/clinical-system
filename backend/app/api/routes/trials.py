from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile

from app.api.errors import AppError, not_found
from app.config import get_settings
from app.rag.pdf_loader import PDFReadError, is_pdf_bytes
from app.schemas.api import PageOut, TrialDetail, TrialSummary
from app.schemas.clinical import Criterion
from app.security.deps import get_current_user
from app.services import audit
from app.services.trials import build_index_task, create_trial_from_pdf, latest_document, load_criteria
from app.storage import ProtocolDocumentRecord, Store, TrialRecord, UserRecord, get_store

router = APIRouter(prefix="/api/trials", tags=["trials"])


def owned_trial(store: Store, trial_id: str, user: UserRecord) -> TrialRecord:
    trial = store.trials.get_owned(trial_id, user.id)
    if trial is None:
        raise not_found("Trial")
    return trial


def _summary(trial: TrialRecord, doc: ProtocolDocumentRecord | None) -> dict:
    return dict(
        id=trial.id, title=trial.title, status=trial.status, index_status=trial.index_status,
        current_version=trial.current_version, protocol_version=doc.protocol_version if doc else None,
        page_count=doc.page_count if doc else None, criteria_count=len(doc.criteria) if doc else 0,
        created_at=trial.created_at,
    )


def _detail(store: Store, trial: TrialRecord) -> TrialDetail:
    doc = latest_document(store, trial)
    return TrialDetail(
        **_summary(trial, doc),
        filename=doc.filename if doc else None,
        extraction_method=doc.extraction_method if doc else None,
        extraction_warnings=doc.extraction_warnings if doc else [],
        criteria=load_criteria(doc),
        error=trial.error,
    )


@router.post("/upload", response_model=TrialDetail, status_code=201)
async def upload_trial(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: UserRecord = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> TrialDetail:
    max_mb = get_settings().max_upload_mb
    limit = max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(413, "FILE_TOO_LARGE", f"Protocol PDF must be at most {max_mb} MB.")
    if not data:
        raise AppError(400, "EMPTY_FILE", "Uploaded file is empty.")
    if not is_pdf_bytes(data):
        raise AppError(400, "INVALID_FILE_TYPE", "Only PDF protocol documents are accepted.",
                       {"filename": file.filename, "content_type": file.content_type})
    name = (file.filename or "protocol.pdf")[:300]
    try:
        trial, doc = create_trial_from_pdf(store, user.id, (title or name.rsplit(".", 1)[0])[:300], name, data)
    except PDFReadError as exc:
        raise AppError(400, "UNREADABLE_PDF", str(exc), {"filename": file.filename}) from exc
    audit.record(store, user.id, "trial.uploaded", "trial", trial.id,
                 {"filename": name, "sha256": doc.sha256, "pages": doc.page_count})
    background.add_task(build_index_task, trial.id, doc.id)
    return _detail(store, trial)


@router.get("", response_model=list[TrialSummary])
def list_trials(user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> list[TrialSummary]:
    trials = sorted(store.trials.for_owner(user.id), key=lambda t: t.created_at, reverse=True)
    return [TrialSummary(**_summary(t, latest_document(store, t))) for t in trials]


@router.get("/{trial_id}", response_model=TrialDetail)
def get_trial(trial_id: str, user: UserRecord = Depends(get_current_user),
              store: Store = Depends(get_store)) -> TrialDetail:
    return _detail(store, owned_trial(store, trial_id, user))


@router.get("/{trial_id}/criteria", response_model=list[Criterion])
def get_criteria(trial_id: str, user: UserRecord = Depends(get_current_user),
                 store: Store = Depends(get_store)) -> list[Criterion]:
    return load_criteria(latest_document(store, owned_trial(store, trial_id, user)))


@router.get("/{trial_id}/pages/{page}", response_model=PageOut)
def get_page(trial_id: str, page: int, user: UserRecord = Depends(get_current_user),
             store: Store = Depends(get_store)) -> PageOut:
    trial = owned_trial(store, trial_id, user)
    doc = latest_document(store, trial)
    if doc is None or page < 1 or page > doc.page_count:
        raise not_found("Page")
    text = next((p["text"] for p in doc.pages if int(p["page"]) == page), "")
    return PageOut(trial_id=trial.id, page=page, page_count=doc.page_count, text=text)
