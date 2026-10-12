"""PostgreSQL persistence with the same interface as the file store.

Each record type has its own table: the columns used for lookups and ownership checks
(``id``, ``owner_id``, ``email``, ``trial_id``, ``status`` …) are real columns with indexes,
and the full validated record is kept in a ``data`` JSONB column so the Pydantic record
types stay the single schema definition. The audit trail is an insert-only table.

``update`` runs ``SELECT … FOR UPDATE`` inside a transaction, so concurrent writers (the
parallel inclusion/exclusion agents report progress at the same time) never lose updates,
and several API workers can share one database.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any, Generic, TypeVar

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.storage.file_store import is_safe_id
from app.storage.records import (
    AuditEvent,
    PatientRecord,
    ProtocolDocumentRecord,
    Record,
    RunRecord,
    TrialRecord,
    UserRecord,
    utcnow,
)

R = TypeVar("R", bound=Record)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS users (
    id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS trials (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES users(id),
    status text NOT NULL,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS trials_owner_idx ON trials (owner_id);

CREATE TABLE IF NOT EXISTS protocol_documents (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES users(id),
    trial_id text NOT NULL REFERENCES trials(id),
    protocol_version text NOT NULL,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS protocol_documents_trial_idx ON protocol_documents (trial_id);

CREATE TABLE IF NOT EXISTS patients (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES users(id),
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS patients_owner_idx ON patients (owner_id);

CREATE TABLE IF NOT EXISTS eligibility_runs (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES users(id),
    trial_id text NOT NULL REFERENCES trials(id),
    patient_id text NOT NULL REFERENCES patients(id),
    status text NOT NULL,
    overall_status text,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS eligibility_runs_owner_idx ON eligibility_runs (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS eligibility_runs_pair_idx ON eligibility_runs (trial_id, patient_id);

CREATE TABLE IF NOT EXISTS audit_events (
    seq bigserial PRIMARY KEY,
    id text NOT NULL UNIQUE,
    owner_id text,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id text,
    details jsonb NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_owner_idx ON audit_events (owner_id, seq);
"""


class PgCollection(Generic[R]):
    """One table of records of one type."""

    def __init__(self, pool: ConnectionPool, table: str, model: type[R], columns: dict[str, Callable[[R], Any]]):
        self._pool = pool
        self.table = table
        self.model = model
        self._columns = columns  # extra indexed columns derived from the record

    def _load(self, row: dict | None) -> R | None:
        return None if row is None else self.model.model_validate(row["data"])

    def _row(self, record: R) -> dict[str, Any]:
        row = {"id": record.id, **{name: fn(record) for name, fn in self._columns.items()}}
        row.update(data=Jsonb(json.loads(record.model_dump_json())),
                   created_at=record.created_at, updated_at=record.updated_at)
        return row

    def _upsert(self, conn, record: R) -> None:
        row = self._row(record)
        cols = ", ".join(row)
        params = ", ".join(f"%({c})s" for c in row)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in row if c not in {"id", "created_at"})
        conn.execute(f"INSERT INTO {self.table} ({cols}) VALUES ({params}) "
                     f"ON CONFLICT (id) DO UPDATE SET {updates}", row)

    def get(self, record_id: str | None) -> R | None:
        if not is_safe_id(record_id):
            return None
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT data FROM {self.table} WHERE id = %s", (record_id,))
            return self._load(cur.fetchone())

    def put(self, record: R) -> R:
        if not is_safe_id(record.id):
            raise ValueError(f"invalid record id: {record.id!r}")
        record.updated_at = utcnow()
        with self._pool.connection() as conn:
            self._upsert(conn, record)
        return record

    def update(self, record_id: str, mutate: Callable[[R], None]) -> R | None:
        """Atomically load, modify and save one record (row lock). Returns None if it does not exist."""
        if not is_safe_id(record_id):
            return None
        with self._pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT data FROM {self.table} WHERE id = %s FOR UPDATE", (record_id,))
            record = self._load(cur.fetchone())
            if record is None:
                return None
            mutate(record)
            record.updated_at = utcnow()
            self._upsert(conn, record)
            return record

    def delete(self, record_id: str) -> bool:
        if not is_safe_id(record_id):
            return False
        with self._pool.connection() as conn:
            return conn.execute(f"DELETE FROM {self.table} WHERE id = %s", (record_id,)).rowcount > 0

    def _select(self, where: str = "", params: tuple = ()) -> list[R]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT data FROM {self.table} {where} ORDER BY id", params)
            return [self.model.model_validate(r["data"]) for r in cur.fetchall()]

    def __iter__(self) -> Iterator[R]:
        return iter(self._select())

    def find(self, predicate: Callable[[R], bool]) -> list[R]:
        return [r for r in self if predicate(r)]

    def first(self, predicate: Callable[[R], bool]) -> R | None:
        return next((r for r in self if predicate(r)), None)

    def where(self, **equals) -> list[R]:
        """Records whose fields equal the given values; indexed columns are filtered in SQL."""
        sql = {k: v for k, v in equals.items() if k in self._columns}
        rows = self._select("WHERE " + " AND ".join(f"{k} = %s" for k in sql), tuple(sql.values())) if sql             else self._select()
        rest = {k: v for k, v in equals.items() if k not in sql}
        return [r for r in rows if all(getattr(r, k) == v for k, v in rest.items())]


class PgOwnedCollection(PgCollection[R]):
    """Table whose rows belong to a user; lookups by another user see nothing."""

    def get_owned(self, record_id: str | None, owner_id: str) -> R | None:
        if not is_safe_id(record_id):
            return None
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT data FROM {self.table} WHERE id = %s AND owner_id = %s", (record_id, owner_id))
            return self._load(cur.fetchone())

    def for_owner(self, owner_id: str) -> list[R]:
        return self._select("WHERE owner_id = %s", (owner_id,))


class PgAuditLog:
    """Insert-only audit trail."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO audit_events (id, owner_id, action, resource_type, resource_id, details, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (event.id, event.owner_id, event.action, event.resource_type, event.resource_id,
                 Jsonb(json.loads(json.dumps(event.details, default=str))), event.created_at),
            )
        return event

    def for_owner(self, owner_id: str) -> list[AuditEvent]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, owner_id, action, resource_type, resource_id, details, created_at "
                        "FROM audit_events WHERE owner_id = %s ORDER BY seq", (owner_id,))
            return [AuditEvent.model_validate(r) for r in cur.fetchall()]


class PostgresStore:
    """All persisted application data in one PostgreSQL database."""

    kind = "postgresql"

    def __init__(self, database_url: str, min_size: int = 1, max_size: int = 10):
        self.root = "postgresql"  # for logging parity with the file store
        self._pool = ConnectionPool(database_url, min_size=min_size, max_size=max_size,
                                    kwargs={"autocommit": True}, open=True)
        self.migrate()
        self.users: PgCollection[UserRecord] = PgCollection(
            self._pool, "users", UserRecord, {"email": lambda u: u.email})
        self.trials: PgOwnedCollection[TrialRecord] = PgOwnedCollection(
            self._pool, "trials", TrialRecord, {"owner_id": lambda t: t.owner_id, "status": lambda t: t.status})
        self.documents: PgOwnedCollection[ProtocolDocumentRecord] = PgOwnedCollection(
            self._pool, "protocol_documents", ProtocolDocumentRecord,
            {"owner_id": lambda d: d.owner_id, "trial_id": lambda d: d.trial_id,
             "protocol_version": lambda d: d.protocol_version})
        self.patients: PgOwnedCollection[PatientRecord] = PgOwnedCollection(
            self._pool, "patients", PatientRecord, {"owner_id": lambda p: p.owner_id})
        self.runs: PgOwnedCollection[RunRecord] = PgOwnedCollection(
            self._pool, "eligibility_runs", RunRecord,
            {"owner_id": lambda r: r.owner_id, "trial_id": lambda r: r.trial_id, "patient_id": lambda r: r.patient_id,
             "status": lambda r: r.status, "overall_status": lambda r: r.overall_status})
        self.audit = PgAuditLog(self._pool)

    def migrate(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(724001)")  # one worker migrates at a time
            conn.execute(SCHEMA)
            conn.execute("INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING", (SCHEMA_VERSION,))

    def user_by_email(self, email: str) -> UserRecord | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT data FROM users WHERE email = %s", (email.lower(),))
            row = cur.fetchone()
            return None if row is None else UserRecord.model_validate(row["data"])

    def is_writable(self) -> bool:
        try:
            with self._pool.connection(timeout=5) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._pool.close()

    def truncate_all(self) -> None:
        """Remove every row (tests only)."""
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE audit_events, eligibility_runs, protocol_documents, patients, trials, users")
