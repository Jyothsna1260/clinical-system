"""File-based persistence. All data lives as JSON documents under ``<DATA_DIR>/store``."""

from functools import lru_cache

from app.config import get_settings
from app.storage.file_store import Store
from app.storage.records import (
    AgentLog,
    AuditEvent,
    PatientRecord,
    PatientVersion,
    ProtocolDocumentRecord,
    RunRecord,
    TrialRecord,
    UserRecord,
    new_id,
    utcnow,
)


@lru_cache
def get_store() -> Store:
    """The process-wide store (also used as a FastAPI dependency)."""
    return Store(get_settings().store_dir)


def reset_store() -> None:
    """Forget the cached store so the next call re-reads settings (used by tests)."""
    get_store.cache_clear()


__all__ = [
    "AgentLog",
    "AuditEvent",
    "PatientRecord",
    "PatientVersion",
    "ProtocolDocumentRecord",
    "RunRecord",
    "Store",
    "TrialRecord",
    "UserRecord",
    "get_store",
    "new_id",
    "reset_store",
    "utcnow",
]
