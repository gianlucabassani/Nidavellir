"""
Unit tests for the SQLite persistence layer (database.Database).

These exercise the real database against a temp file (configured in conftest)
and need no external services — they are the fast, always-runnable core of the
suite.
"""
import json
import uuid

import pytest

from database import Database


@pytest.fixture()
def db():
    return Database()


def _new_id():
    return str(uuid.uuid4())


def test_singleton_returns_same_instance():
    assert Database() is Database()


def test_create_and_get_roundtrip(db):
    dep_id = _new_id()
    db.create_deployment(dep_id, user_id="lab-team-1", scenario="basic_pentest")

    row = db.get_deployment(dep_id)
    assert row is not None
    assert row["id"] == dep_id
    assert row["user_id"] == "lab-team-1"
    assert row["scenario"] == "basic_pentest"
    assert row["status"] == "pending"
    assert row["outputs"] == "{}"


def test_get_missing_returns_none(db):
    assert db.get_deployment("does-not-exist") is None


def test_update_status_and_outputs(db):
    dep_id = _new_id()
    db.create_deployment(dep_id, "lab", "basic_pentest")

    outputs = {"attack_vm_floating_ip": "192.168.1.80"}
    db.update_deployment(dep_id, status="deploying")
    db.update_deployment(dep_id, status="active", outputs=outputs)

    row = db.get_deployment(dep_id)
    assert row["status"] == "active"
    assert json.loads(row["outputs"]) == outputs


def test_update_records_error(db):
    dep_id = _new_id()
    db.create_deployment(dep_id, "lab", "basic_pentest")

    db.update_deployment(dep_id, status="failed", error="terraform apply failed")

    row = db.get_deployment(dep_id)
    assert row["status"] == "failed"
    assert row["error"] == "terraform apply failed"


def test_list_returns_created_deployments(db):
    ids = {_new_id() for _ in range(3)}
    for dep_id in ids:
        db.create_deployment(dep_id, "lab", "basic_pentest")

    listed_ids = {row["id"] for row in db.list_deployments()}
    assert ids.issubset(listed_ids)


def test_delete_removes_deployment(db):
    dep_id = _new_id()
    db.create_deployment(dep_id, "lab", "basic_pentest")
    assert db.get_deployment(dep_id) is not None

    db.delete_deployment(dep_id)
    assert db.get_deployment(dep_id) is None


def test_update_does_not_silently_drop_falsy_status(db):
    """Audit #13: `if status:` silently ignored empty strings. With the
    ADR-0004 state machine an empty status is rejected LOUDLY, never dropped."""
    from states import IllegalTransition

    dep_id = _new_id()
    db.create_deployment(dep_id, "lab", "basic_pentest")

    with pytest.raises(IllegalTransition):
        db.update_deployment(dep_id, status="")
    assert db.get_deployment(dep_id)["status"] == "pending"

    # None still means "leave the column alone"
    db.update_deployment(dep_id, status="deploying")
    db.update_deployment(dep_id, outputs={"k": "v"})
    assert db.get_deployment(dep_id)["status"] == "deploying"


def test_purge_deployments_removes_only_given_statuses(db):
    terminal, live = _new_id(), _new_id()
    db.create_deployment(terminal, "lab", "basic_pentest")
    db.update_deployment(terminal, status="destroying")
    db.update_deployment(terminal, status="destroyed")
    db.create_deployment(live, "lab", "basic_pentest")
    db.update_deployment(live, status="deploying")
    db.update_deployment(live, status="active")

    removed = db.purge_deployments(("destroyed", "failed"))

    assert removed >= 1
    assert db.get_deployment(terminal) is None
    assert db.get_deployment(live) is not None
