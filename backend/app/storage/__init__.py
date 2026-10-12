"""Persistence. PostgreSQL when ``DATABASE_URL`` is set, otherwise JSON documents under ``<DATA_DIR>/store``.

Both backends expose the same collections (users, trials, documents, patients, runs) and audit log,
so services never know which one is in use.
"""

from functools import lru_cache
from typing import TYPE_CHECKING, Union

from app.config import get_settings
from app.storage.file_store import Store as FileStore
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

if TYPE_CHECKING:
    from app.storage.postgres_store import PostgresStore

Store = Union[FileStore, "PostgresStore"]


@lru_cache
def get_store() -> Store:
    """The process-wide store (also used as a FastAPI dependency)."""
    settings = get_settings()
    if settings.database_url:
        from app.storage.postgres_store import PostgresStore

        return PostgresStore(settings.database_url)
    return FileStore(settings.store_dir)


def reset_store() -> None:
    """Forget the cached store so the next call re-reads settings (used by tests)."""
    if get_store.cache_info().currsize:
        close = getattr(get_store(), "close", None)
        if close:
            close()
    get_store.cache_clear()


__all__ = [
    "AgentLog",
    "AuditEvent",
    "FileStore",
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
