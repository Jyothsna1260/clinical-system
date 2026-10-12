"""Workflow state: Redis (via fakeredis) and in-memory backends, and the fallback when Redis is down."""

from datetime import UTC, datetime

import fakeredis
import pytest

from app.state.run_state import FallbackRunState, MemoryRunState, RedisRunState


@pytest.fixture(params=["memory", "redis"])
def run_state(request):
    if request.param == "memory":
        return MemoryRunState()
    return RedisRunState(fakeredis.FakeRedis(decode_responses=True), ttl_seconds=60)


def test_records_and_reads_node_progress(run_state):
    started = datetime(2026, 10, 1, tzinfo=UTC)
    run_state.record_node("r1", "extract_protocol", {"status": "running", "started_at": started, "summary": None})
    run_state.record_node("r1", "extract_protocol", {"status": "completed", "started_at": started,
                                                     "summary": {"criteria": 4}})
    run_state.record_node("r2", "persist", {"status": "running"})
    nodes = run_state.nodes("r1")
    assert list(nodes) == ["extract_protocol"]
    assert nodes["extract_protocol"]["status"] == "completed"
    assert nodes["extract_protocol"]["summary"] == {"criteria": 4}
    assert nodes["extract_protocol"]["started_at"] == started.isoformat()
    run_state.clear("r1")
    assert run_state.nodes("r1") == {} and "persist" in run_state.nodes("r2")


def test_redis_entries_expire():
    client = fakeredis.FakeRedis(decode_responses=True)
    RedisRunState(client, ttl_seconds=60).record_node("r1", "persist", {"status": "running"})
    assert 0 < client.ttl("cte:run:r1:nodes") <= 60


def test_falls_back_to_memory_when_redis_is_down():
    server = fakeredis.FakeServer()
    server.connected = False
    state = FallbackRunState(RedisRunState(fakeredis.FakeRedis(server=server, decode_responses=True)))
    state.record_node("r1", "persist", {"status": "completed"})
    assert state.nodes("r1")["persist"]["status"] == "completed"
    assert state.kind.startswith("memory")


def test_analysis_progress_flows_through_redis(client, auth_headers, fixture_path, load_patient, monkeypatch):
    """A full API run with Redis as the workflow-state backend; agent logs end up in the durable record."""
    from app.services import analysis, eligibility
    from app.storage import get_store
    from tests.test_api import _patient, _upload

    redis_state = RedisRunState(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(analysis, "get_run_state", lambda: redis_state)
    monkeypatch.setattr(eligibility, "get_run_state", lambda: redis_state)

    h = auth_headers()
    trial = _upload(client, h, fixture_path)
    patient = _patient(client, h, load_patient)
    run_id = client.post("/api/eligibility/analyze", headers=h,
                         json={"trial_id": trial["id"], "patient_id": patient["id"]}).json()["run_id"]

    live = redis_state.nodes(run_id)
    assert live["review_and_decide"]["summary"]["overall_status"] == "NOT_ELIGIBLE"
    assert live["persist"]["status"] == "completed"
    record = get_store().runs.get(run_id)
    assert set(record.agent_logs) == set(live)
    status = client.get(f"/api/eligibility/{run_id}/status", headers=h).json()
    assert {p["node"]: p["status"] for p in status["progress"]}["web_research"] == "completed"
