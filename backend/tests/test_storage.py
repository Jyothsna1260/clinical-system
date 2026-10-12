"""File store: round-trips, ownership scoping, atomic writes and the audit log."""

import threading

import pytest

from app.storage import AuditEvent, FileStore, PatientRecord, PatientVersion, TrialRecord, UserRecord


@pytest.fixture
def store(tmp_path) -> FileStore:
    return FileStore(tmp_path / "store")


def test_records_survive_reopening(store, tmp_path):
    user = store.users.put(UserRecord(email="a@example.org", hashed_password="x"))
    trial = store.trials.put(TrialRecord(owner_id=user.id, title="Renal"))

    reopened = FileStore(tmp_path / "store")
    assert reopened.users.get(user.id).email == "a@example.org"
    assert reopened.trials.get(trial.id).title == "Renal"
    assert reopened.user_by_email("A@Example.org").id == user.id


def test_owned_lookup_hides_other_users_records(store):
    trial = store.trials.put(TrialRecord(owner_id="user-a", title="T"))
    assert store.trials.get_owned(trial.id, "user-a") is not None
    assert store.trials.get_owned(trial.id, "user-b") is None
    assert store.trials.for_owner("user-b") == []


@pytest.mark.parametrize("bad_id", ["../users/x", "a/b", "", None, "x" * 65, "a.json"])
def test_unsafe_ids_are_never_resolved(store, bad_id):
    assert store.trials.get(bad_id) is None
    assert store.trials.delete(bad_id) is False


def test_update_is_atomic_under_concurrency(store):
    patient = store.patients.put(PatientRecord(owner_id="u", versions=[PatientVersion(version=1, label="p", data={})]))

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


def test_no_temp_files_left_behind(store):
    store.trials.put(TrialRecord(owner_id="u", title="T"))
    assert not list(store.trials.root.glob("*.tmp"))


def test_update_missing_record_returns_none(store):
    assert store.trials.update("does-not-exist", lambda t: None) is None


def test_audit_log_is_append_only_per_owner(store):
    store.audit.append(AuditEvent(owner_id="u1", action="a", resource_type="trial"))
    store.audit.append(AuditEvent(owner_id="u1", action="b", resource_type="trial"))
    store.audit.append(AuditEvent(owner_id="u2", action="c", resource_type="trial"))
    assert [e.action for e in store.audit.for_owner("u1")] == ["a", "b"]
    assert [e.action for e in store.audit.for_owner("u2")] == ["c"]
    assert store.audit.for_owner("nobody") == []
