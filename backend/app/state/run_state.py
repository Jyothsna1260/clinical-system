"""Live workflow state for eligibility runs: per-agent progress and each agent's output summary.

While a run executes, every LangGraph node reports here (start, finish, status, output summary).
This is the hot, concurrently written state (the inclusion and exclusion agents run in parallel),
so it lives in Redis when ``REDIS_URL`` is set and in process memory otherwise. Entries expire
after ``RUN_STATE_TTL_SECONDS``. When the run ends, the analysis service copies the final agent
logs into the durable run record (PostgreSQL or the file store), which remains the source of truth.

Redis layout::

    cte:run:<run_id>:nodes   hash  node -> JSON {status, started_at, ended_at, summary}
"""

import contextlib
import json
import logging
import threading
from datetime import datetime
from typing import Any, Protocol

log = logging.getLogger(__name__)


def _encode(entry: dict[str, Any]) -> str:
    return json.dumps(entry, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v))


class RunState(Protocol):
    kind: str

    def record_node(self, run_id: str, node: str, entry: dict[str, Any]) -> None: ...

    def nodes(self, run_id: str) -> dict[str, dict[str, Any]]: ...

    def clear(self, run_id: str) -> None: ...

    def ping(self) -> bool: ...


class MemoryRunState:
    """In-process run state (single API worker)."""

    kind = "memory"

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def record_node(self, run_id: str, node: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._runs.setdefault(run_id, {})[node] = json.loads(_encode(entry))

    def nodes(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._runs.get(run_id, {}).items()}

    def clear(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)

    def ping(self) -> bool:
        return True


class RedisRunState:
    """Run state shared by every API worker through Redis."""

    kind = "redis"

    def __init__(self, client, ttl_seconds: int = 86400, prefix: str = "cte:run:"):
        self._r = client
        self._ttl = ttl_seconds
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str, ttl_seconds: int = 86400) -> "RedisRunState":
        import redis

        return cls(redis.Redis.from_url(url, decode_responses=True, socket_timeout=5), ttl_seconds)

    def _key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}:nodes"

    def record_node(self, run_id: str, node: str, entry: dict[str, Any]) -> None:
        key = self._key(run_id)
        pipe = self._r.pipeline()
        pipe.hset(key, node, _encode(entry))
        pipe.expire(key, self._ttl)
        pipe.execute()

    def nodes(self, run_id: str) -> dict[str, dict[str, Any]]:
        return {node: json.loads(raw) for node, raw in (self._r.hgetall(self._key(run_id)) or {}).items()}

    def clear(self, run_id: str) -> None:
        self._r.delete(self._key(run_id))

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


class FallbackRunState:
    """Redis first; if Redis is unreachable, keep the run going with in-process state."""

    def __init__(self, primary: RedisRunState):
        self._primary = primary
        self._fallback = MemoryRunState()

    @property
    def kind(self) -> str:
        return "redis" if self._primary.ping() else "memory (redis unavailable)"

    def record_node(self, run_id: str, node: str, entry: dict[str, Any]) -> None:
        try:
            self._primary.record_node(run_id, node, entry)
        except Exception as exc:
            log.warning("redis unavailable, recording %s/%s in memory: %s", run_id, node, exc)
            self._fallback.record_node(run_id, node, entry)

    def nodes(self, run_id: str) -> dict[str, dict[str, Any]]:
        try:
            primary = self._primary.nodes(run_id)
        except Exception:
            primary = {}
        return {**self._fallback.nodes(run_id), **primary}

    def clear(self, run_id: str) -> None:
        self._fallback.clear(run_id)
        with contextlib.suppress(Exception):  # entries expire on their own if Redis is unreachable
            self._primary.clear(run_id)

    def ping(self) -> bool:
        return self._primary.ping()
