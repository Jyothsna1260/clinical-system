"""Workflow state for running analyses (Redis when configured, otherwise in-process memory)."""

from functools import lru_cache

from app.config import get_settings
from app.state.run_state import FallbackRunState, MemoryRunState, RedisRunState, RunState


@lru_cache
def get_run_state() -> RunState:
    settings = get_settings()
    if settings.redis_url:
        return FallbackRunState(RedisRunState.from_url(settings.redis_url, settings.run_state_ttl_seconds))
    return MemoryRunState()


def reset_run_state() -> None:
    get_run_state.cache_clear()


__all__ = ["FallbackRunState", "MemoryRunState", "RedisRunState", "RunState", "get_run_state", "reset_run_state"]
