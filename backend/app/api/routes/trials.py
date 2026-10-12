from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas.api import PageOut, TrialDetail, TrialSummary
from app.schemas.clinical import Criterion
from app.security.deps import get_current_user
from app.services import trials
from app.storage import Store, UserRecord, get_store

router = APIRouter(prefix="/api/trials", tags=["trials"])


@router.post("/upload", response_model=TrialDetail, status_code=201)
async def upload_trial(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: UserRecord = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> TrialDetail:
    # Read one byte past the limit so oversized files are detected without loading them fully.
    data = await file.read(trials.max_upload_bytes() + 1)
    # PDF parsing and the LLM extraction call are blocking; run them in a worker thread so the event
    # loop keeps serving other requests (status polling, health checks) during a long upload.
    trial, doc = await run_in_threadpool(
        trials.upload_protocol, store, user.id, file.filename, file.content_type, title, data
    )
    background.add_task(trials.build_index_task, trial.id, doc.id)
    return await run_in_threadpool(trials.trial_detail, store, trial)


@router.get("", response_model=list[TrialSummary])
def list_trials(user: UserRecord = Depends(get_current_user), store: Store = Depends(get_store)) -> list[TrialSummary]:
    return trials.list_trials(store, user.id)


@router.get("/{trial_id}", response_model=TrialDetail)
def get_trial(trial_id: str, user: UserRecord = Depends(get_current_user),
              store: Store = Depends(get_store)) -> TrialDetail:
    return trials.trial_detail(store, trials.require_trial(store, trial_id, user.id))


@router.get("/{trial_id}/criteria", response_model=list[Criterion])
def get_criteria(trial_id: str, user: UserRecord = Depends(get_current_user),
                 store: Store = Depends(get_store)) -> list[Criterion]:
    trial = trials.require_trial(store, trial_id, user.id)
    return trials.load_criteria(trials.latest_document(store, trial))


@router.get("/{trial_id}/pages/{page}", response_model=PageOut)
def get_page(trial_id: str, page: int, user: UserRecord = Depends(get_current_user),
             store: Store = Depends(get_store)) -> PageOut:
    return trials.get_page(store, trial_id, user.id, page)
