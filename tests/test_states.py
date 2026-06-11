"""
Lab lifecycle state machine + events audit stream (ADR-0004).

Pins the legal-transition graph, the LOUD failure on illegal writes, the 409
on destroying an already-destroyed lab, and the audit events appended on
create / transition / record deletion.
"""
import uuid

import pytest

pytest.importorskip("sqlalchemy")

from database import Database  # noqa: E402
from states import IllegalTransition, LabStatus, validate_transition  # noqa: E402


def test_full_happy_path_is_legal():
    chain = ["pending", "deploying", "active", "destroying", "destroyed"]
    for current, new in zip(chain, chain[1:]):
        validate_transition(current, new)


def test_failure_and_retry_edges_are_legal():
    validate_transition("pending", "failed")
    validate_transition("deploying", "failed")
    validate_transition("active", "failed")
    validate_transition("failed", "destroying")
    validate_transition("destroying", "error_destroying")
    validate_transition("error_destroying", "destroying")
    # destroy may be requested from any live state (stuck-pending rescue)
    validate_transition("pending", "destroying")
    validate_transition("deploying", "destroying")


def test_same_state_reassertion_is_allowed():
    for status in LabStatus:
        validate_transition(status, status)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("destroyed", "active"),      # resurrection
        ("destroyed", "destroying"),  # re-destroy of a terminal lab
        ("pending", "active"),        # skipping deploying
        ("active", "pending"),        # going backwards
        ("failed", "active"),         # failure is not self-healing
        ("active", ""),               # empty string (audit #13 family)
        ("active", "bogus"),          # unknown status
    ],
)
def test_illegal_transitions_raise(current, new):
    with pytest.raises(IllegalTransition):
        validate_transition(current, new)


def _lab(db, *steps):
    lab_id = str(uuid.uuid4())
    db.create_deployment(lab_id, "state-test", "basic_pentest", actor="tester")
    for step in steps:
        db.update_deployment(lab_id, status=step, actor="tester")
    return lab_id


def test_destroy_endpoint_409_on_destroyed_lab():
    import api
    import auth
    from fastapi.testclient import TestClient

    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name="state-tests", role="admin")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key

    lab_id = _lab(db, "destroying", "destroyed")
    resp = client.delete(f"/destroy/{lab_id}")
    assert resp.status_code == 409
    assert "destroyed" in resp.json()["detail"]


def test_events_record_lifecycle_with_actor():
    db = Database()
    lab_id = _lab(db, "deploying", "active")

    events = db.list_events(lab_id=lab_id)
    types = [e["type"] for e in events]
    assert types.count("created") == 1
    assert types.count("status") == 2
    assert all(e["actor"] == "tester" for e in events)

    transitions = {(e["payload"]["from"], e["payload"]["to"])
                   for e in events if e["type"] == "status"}
    assert transitions == {("pending", "deploying"), ("deploying", "active")}


def test_events_survive_record_deletion():
    db = Database()
    lab_id = _lab(db, "destroying", "destroyed")
    db.delete_deployment(lab_id, actor="tester")

    assert db.get_deployment(lab_id) is None
    events = db.list_events(lab_id=lab_id)
    assert [e["type"] for e in events][0] == "record_deleted"
    assert len(events) >= 4  # created + 2 transitions + record_deleted


def test_unchanged_status_appends_no_event():
    db = Database()
    lab_id = _lab(db, "deploying")
    before = len(db.list_events(lab_id=lab_id))
    db.update_deployment(lab_id, status="deploying")  # idempotent re-assert
    assert len(db.list_events(lab_id=lab_id)) == before
