from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.config import HUMAN_REVIEW_NOTICE, get_settings
from app.storage import Store, get_store

router = APIRouter(tags=["health"])


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """The backend is API-only; send browsers to the interactive docs."""
    return RedirectResponse("/docs")


@router.get("/api/health")
def health(store: Store = Depends(get_store)) -> dict:
    s = get_settings()
    storage_ok = store.is_writable()
    return {
        "status": "ok" if storage_ok else "degraded",
        "storage": "ok" if storage_ok else "unavailable",
        "llm_provider": s.llm_provider if s.llm_enabled else "none (rule-based fallback)",
        "embeddings_enabled": s.embeddings_enabled,
        "human_review_notice": HUMAN_REVIEW_NOTICE,
    }
