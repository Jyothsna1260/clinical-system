"""PostgreSQL store: same behaviour as the file store. Runs only when TEST_DATABASE_URL is set."""

import os
import threading

import pytest

from app.storage import AuditEvent, PatientRecord, PatientVersion, RunRecord, TrialRecord, UserRecord

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def store():
    from app.storage.postgres_store import PostgresStore

    s = PostgresStore(DATABASE_URL)
    s.truncate_all()
    yield s
    s.truncate_all()
    s.close()


@pytest.fixture
def user(store) -> UserRecord:
    return store.users.put(UserRecord(email="a@example.org", hashed_password="x"))


def test_records_round_trip_and_email_lookup(store, user):
    trial = store.trials.put(TrialRecord(owner_id=user.id, title="Renal"))
    assert store.trials.get(trial.id).title == "Renal"
    assert store.user_by_email("A@Example.org").id == user.id
    assert store.user_by_email("nobody@example.org") is None


def test_owned_lookup_hides_other_users_records(store, user):
    other = store.users.put(UserRecord(email="b@example.org", hashed_password="x"))
    trial = store.trials.put(TrialRecord(owner_id=user.id, title="T"))
    assert store.trials.get_owned(trial.id, user.id) is not None
    assert store.trials.get_owned(trial.id, other.id) is None
    assert store.trials.for_owner(other.id) == []


@pytest.mark.parametrize("bad_id", ["../users/x", "a/b", "", None, "x" * 65, "a'; DROP TABLE users; --"])
def test_unsafe_ids_are_never_resolved(store, bad_id):
    assert store.trials.get(bad_id) is None
    assert store.trials.delete(bad_id) is False


def test_update_is_atomic_under_concurrency(store, user):
    patient = store.patients.put(PatientRecord(owner_id=user.id, versions=[PatientVersion(version=1, label="p", data={})]))

    def add_version() -> None:
        def apply(p: PatientRecord) -> None:
            p.versions = [*p.versions, PatientVersion(version=p.latest.version + 1, label="p", data={})]
        store.patients.update(patient.id, apply)

    threads = [threading.Thread(target=add_version) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [v.version for v in store.patients.get(patient.id).versions] == list(range(1, 22))


def test_indexed_columns_follow_updates(store, user):
    trial = store.trials.put(TrialRecord(owner_id=user.id, title="T"))
    patient = store.patients.put(PatientRecord(owner_id=user.id, versions=[PatientVersion(version=1, label="p", data={})]))
    run = store.runs.put(RunRecord(owner_id=user.id, trial_id=trial.id, document_id="d", protocol_version="v1",
                                   patient_id=patient.id, patient_profile_id="pp", patient_profile_version=1))
    store.runs.update(run.id, lambda r: setattr(r, "status", "completed"))
    assert [r.id for r in store.runs.where(trial_id=trial.id, status="completed")] == [run.id]
    assert store.runs.where(trial_id=trial.id, status="queued") == []


def test_update_missing_record_returns_none(store):
    assert store.trials.update("does-not-exist", lambda t: None) is None


def test_audit_log_is_append_only_per_owner(store):
    store.audit.append(AuditEvent(owner_id="u1", action="a", resource_type="trial", details={"n": 1}))
    store.audit.append(AuditEvent(owner_id="u1", action="b", resource_type="trial"))
    store.audit.append(AuditEvent(owner_id="u2", action="c", resource_type="trial"))
    events = store.audit.for_owner("u1")
    assert [e.action for e in events] == ["a", "b"]
    assert events[0].details == {"n": 1}
    assert store.audit.for_owner("nobody") == []


def test_health_check(store):
    assert store.is_writable() is True
