"""Local file storage: one JSON document per record, written atomically.

Layout under ``<DATA_DIR>/store``::

    users/<id>.json  trials/<id>.json  documents/<id>.json  patients/<id>.json  runs/<id>.json
    audit/<owner_id>.jsonl   (append-only)

Writes go to a temporary file in the same directory and are then swapped in with
``os.replace``, so a crash never leaves a half-written record. A process-wide re-entrant
lock serializes read-modify-write cycles. The store is designed for a single API process
(``uvicorn --workers 1``); run several workers only behind a shared database.
"""

import json
import os
import re
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Generic, TypeVar

from app.storage.records import (
    AuditEvent,
    OwnedRecord,
    PatientRecord,
    ProtocolDocumentRecord,
    Record,
    RunRecord,
    TrialRecord,
    UserRecord,
    utcnow,
)

R = TypeVar("R", bound=Record)

# Record ids are UUIDs; anything else (e.g. "../x" from a URL) is treated as not found.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_safe_id(value: str | None) -> bool:
    return bool(value) and bool(_SAFE_ID.match(value))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Collection(Generic[R]):
    """A directory of JSON documents of one record type."""

    def __init__(self, root: Path, model: type[R], lock: threading.RLock):
        self.root = root
        self.model = model
        self._lock = lock
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, record_id: str) -> Path:
        return self.root / f"{record_id}.json"

    def get(self, record_id: str | None) -> R | None:
        if not is_safe_id(record_id):
            return None
        path = self._path(record_id)
        with self._lock:
            if not path.exists():
                return None
            return self.model.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, record: R) -> R:
        if not is_safe_id(record.id):
            raise ValueError(f"invalid record id: {record.id!r}")
        record.updated_at = utcnow()
        with self._lock:
            atomic_write_text(self._path(record.id), record.model_dump_json(indent=2))
        return record

    def update(self, record_id: str, mutate: Callable[[R], None]) -> R | None:
        """Atomically load, modify and save one record. Returns None if it does not exist."""
        with self._lock:
            record = self.get(record_id)
            if record is None:
                return None
            mutate(record)
            return self.put(record)

    def delete(self, record_id: str) -> bool:
        if not is_safe_id(record_id):
            return False
        with self._lock:
            path = self._path(record_id)
            existed = path.exists()
            path.unlink(missing_ok=True)
            return existed

    def __iter__(self) -> Iterator[R]:
        with self._lock:
            paths = sorted(self.root.glob("*.json"))
            records = [self.model.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
        return iter(records)

    def find(self, predicate: Callable[[R], bool]) -> list[R]:
        return [r for r in self if predicate(r)]

    def first(self, predicate: Callable[[R], bool]) -> R | None:
        return next((r for r in self if predicate(r)), None)


class OwnedCollection(Collection[R]):
    """Collection whose records belong to a user; lookups by another user see nothing."""

    def get_owned(self, record_id: str | None, owner_id: str) -> R | None:
        record = self.get(record_id)
        if record is None or not isinstance(record, OwnedRecord) or record.owner_id != owner_id:
            return None
        return record

    def for_owner(self, owner_id: str) -> list[R]:
        return self.find(lambda r: r.owner_id == owner_id)


class AuditLog:
    """Append-only audit trail, one JSON Lines file per owner."""

    def __init__(self, root: Path, lock: threading.RLock):
        self.root = root
        self._lock = lock
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, owner_id: str | None) -> Path:
        return self.root / f"{owner_id if is_safe_id(owner_id) else '_system'}.jsonl"

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._lock, self._path(event.owner_id).open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")
        return event

    def for_owner(self, owner_id: str) -> list[AuditEvent]:
        path = self._path(owner_id)
        with self._lock:
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
        return [AuditEvent.model_validate(json.loads(line)) for line in lines if line.strip()]


class Store:
    """All persisted application data, rooted at one directory on local disk."""

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()
        self.users: Collection[UserRecord] = Collection(root / "users", UserRecord, self._lock)
        self.trials: OwnedCollection[TrialRecord] = OwnedCollection(root / "trials", TrialRecord, self._lock)
        self.documents: OwnedCollection[ProtocolDocumentRecord] = OwnedCollection(
            root / "documents", ProtocolDocumentRecord, self._lock
        )
        self.patients: OwnedCollection[PatientRecord] = OwnedCollection(root / "patients", PatientRecord, self._lock)
        self.runs: OwnedCollection[RunRecord] = OwnedCollection(root / "runs", RunRecord, self._lock)
        self.audit = AuditLog(root / "audit", self._lock)

    def user_by_email(self, email: str) -> UserRecord | None:
        email = email.lower()
        return self.users.first(lambda u: u.email == email)

    def is_writable(self) -> bool:
        try:
            atomic_write_text(self.root / ".healthcheck", utcnow().isoformat())
            return True
        except OSError:
            return False
