"""
Tests for deployment-record management (archive cleanup).

Pins: DELETE /deployments/{id} removes only terminal-state records
(destroyed/failed/error_destroying), DELETE /deployments purges all of
them at once, and live labs are protected by a 409.
"""
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from database import Database  # noqa: E402


@pytest.fixture()
def client():
    import api

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="rec-tests", role="admin")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


# Shortest legal path from 'pending' to each state (the state machine
# rejects arbitrary jumps since ADR-0004)
_PATHS = {
    "pending": [],
    "deploying": ["deploying"],
    "active": ["deploying", "active"],
    "failed": ["failed"],
    "destroying": ["destroying"],
    "destroyed": ["destroying", "destroyed"],
    "error_destroying": ["destroying", "error_destroying"],
}


def _make_deployment(status):
    db = Database()
    system_id = str(uuid.uuid4())
    db.create_deployment(system_id, f"rec-{status}", "basic_pentest")
    for step in _PATHS[status]:
        db.update_deployment(system_id, status=step)
    return system_id


def test_delete_destroyed_record(client):
    system_id = _make_deployment("destroyed")
    resp = client.delete(f"/deployments/{system_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}
    assert Database().get_deployment(system_id) is None


def test_delete_failed_record(client):
    system_id = _make_deployment("failed")
    assert client.delete(f"/deployments/{system_id}").status_code == 200
    assert Database().get_deployment(system_id) is None


def test_delete_live_record_rejected(client):
    for status in ("pending", "deploying", "active", "destroying"):
        system_id = _make_deployment(status)
        resp = client.delete(f"/deployments/{system_id}")
        assert resp.status_code == 409, status
        assert "destroy it first" in resp.json()["detail"]
        assert Database().get_deployment(system_id) is not None


def test_delete_unknown_record_404(client):
    assert client.delete(f"/deployments/{uuid.uuid4()}").status_code == 404


def test_purge_removes_only_terminal_records(client):
    db = Database()
    destroyed = _make_deployment("destroyed")
    failed = _make_deployment("failed")
    error_destroying = _make_deployment("error_destroying")
    active = _make_deployment("active")
    pending = _make_deployment("pending")

    resp = client.delete("/deployments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "purged"
    # At least our three terminal records went away (other tests may have
    # contributed more); the live ones must survive.
    assert body["deleted"] >= 3
    assert db.get_deployment(destroyed) is None
    assert db.get_deployment(failed) is None
    assert db.get_deployment(error_destroying) is None
    assert db.get_deployment(active) is not None
    assert db.get_deployment(pending) is not None


def test_delete_requires_auth():
    import api

    anon = TestClient(api.app)
    assert anon.delete(f"/deployments/{uuid.uuid4()}").status_code == 401
    assert anon.delete("/deployments").status_code == 401
