"""Fixed-window rate limiting for the authentication endpoints.

Each attempt increments a counter for (bucket, identity, current minute); when the counter passes the
limit the request is refused with 429 RATE_LIMITED. Counters live in Redis when ``REDIS_URL`` is set
(shared by every API worker) and in process memory otherwise.
"""

import logging
import threading
import time
from functools import lru_cache
from typing import Protocol

from fastapi import Request

from app.config import get_settings
from app.errors import AppError

log = logging.getLogger(__name__)

WINDOW_SECONDS = 60


class Counter(Protocol):
    def hit(self, key: str) -> int:
        """Increment the counter for key in the current window and return its value."""
        ...


class MemoryCounter:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int:
        window = int(time.time() // WINDOW_SECONDS)
        with self._lock:
            # Drop counters from earlier windows so memory stays bounded.
            if len(self._counts) > 10_000:
                self._counts = {k: v for k, v in self._counts.items() if k.endswith(f":{window}")}
            full = f"{key}:{window}"
            self._counts[full] = self._counts.get(full, 0) + 1
            return self._counts[full]


class RedisCounter:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
        self._fallback = MemoryCounter()

    def hit(self, key: str) -> int:
        full = f"cte:ratelimit:{key}:{int(time.time() // WINDOW_SECONDS)}"
        try:
            pipe = self._r.pipeline()
            pipe.incr(full)
            pipe.expire(full, WINDOW_SECONDS * 2)
            return int(pipe.execute()[0])
        except Exception as exc:  # Redis down: keep limiting per process rather than failing open
            log.warning("rate limiter falling back to memory: %s", exc)
            return self._fallback.hit(key)


@lru_cache
def get_counter() -> Counter:
    url = get_settings().redis_url
    return RedisCounter(url) if url else MemoryCounter()


def reset_counter() -> None:
    get_counter.cache_clear()


def client_ip(request: Request) -> str:
    # uvicorn runs with --proxy-headers, so request.client is the real client behind Render's proxy.
    return request.client.host if request.client else "unknown"


def enforce(bucket: str, *identities: str) -> None:
    """Count one attempt against each identity; raise 429 if any is over the per-minute limit."""
    limit = get_settings().auth_rate_limit_per_minute
    if limit <= 0:
        return
    counter = get_counter()
    for identity in identities:
        if counter.hit(f"{bucket}:{identity}") > limit:
            raise AppError(429, "RATE_LIMITED", "Too many attempts. Please wait a minute and try again.",
                           {"retry_after_seconds": WINDOW_SECONDS})
