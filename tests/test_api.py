"""
API-layer tests using FastAPI's TestClient.

The Celery dispatch (`.delay`) is stubbed so these run with no Redis/worker —
we assert the HTTP contract and the synchronous DB side effects, not the async
provisioning (that belongs in an integration test against a live worker).
"""
import uuid

import pytest

# fastapi/starlette are heavier deps; skip cleanly if the env lacks them
# (they are installed in CI via requirements-dev.txt).
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class _FakeTask:
    """Stand-in for a Celery task: records the last dispatch, never hits Redis."""

    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return None


@pytest.fixture()
def client(monkeypatch):
    """Authenticated test client (a fresh API key per test, ADR-0002)."""
    import api
    import auth
    from database import Database

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    monkeypatch.setattr(api, "destroy_lab", _FakeTask())

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="tests", role="admin")

    test_client = TestClient(api.app)
    test_client.headers["X-API-Key"] = key
    return test_client


def test_list_deployments_ok(client):
    resp = client.get("/deployments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_deploy_accepts_and_persists_pending(client):
    resp = client.post(
        "/deploy", json={"scenario": "basic_pentest", "instance_id": "lab-team-1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    system_id = body["instance_id"]

    # A pending record should now be queryable by its generated UUID.
    status = client.get(f"/status/{system_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["status"] == "pending"
    assert data["user_id"] == "lab-team-1"
    assert data["scenario"] == "basic_pentest"


def test_status_unknown_returns_404(client):
    resp = client.get(f"/status/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_destroy_unknown_returns_404(client):
    resp = client.delete(f"/destroy/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_destroy_known_marks_destroying(client):
    deployed = client.post(
        "/deploy", json={"scenario": "basic_pentest", "instance_id": "lab-x"}
    ).json()
    system_id = deployed["instance_id"]

    resp = client.delete(f"/destroy/{system_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert client.get(f"/status/{system_id}").json()["status"] == "destroying"
