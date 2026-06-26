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


def test_providers_reports_active_default(client):
    body = client.get("/providers").json()
    assert "default" in body
    assert {p["name"] for p in body["providers"]} >= {"mock", "docker-local"}


def test_events_endpoints_expose_the_audit_trail(client):
    # A deploy records a synchronous 'created' event (the dispatch is stubbed).
    sysid = client.post(
        "/deploy", json={"scenario": "basic_pentest", "instance_id": "evt-lab"}
    ).json()["instance_id"]

    per_arena = client.get(f"/deployments/{sysid}/events")
    assert per_arena.status_code == 200
    events = per_arena.json()["events"]
    assert any(e["type"] == "created" for e in events)
    assert all(e["lab_id"] == sysid for e in events)

    glob = client.get("/events?limit=20")
    assert glob.status_code == 200
    assert any(e["lab_id"] == sysid for e in glob.json()["events"])


def test_arena_events_404_for_unknown_arena(client):
    resp = client.get(f"/deployments/{uuid.uuid4()}/events")
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


# --- deploy-time hallucinated-image gate (docker-local only) -------------------


def _import_container_scenario(client, sid, victim_image):
    spec = {
        "schema": "nidavellir/v3",
        "name": sid,
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [
            {"name": "victim", "role": "victim", "image": victim_image,
             "segments": ["lab"], "ports": [80]},
            {"name": "attacker", "role": "attacker", "image": "kali",
             "segments": ["lab"], "entrypoint": True},
        ],
        "agents": [{"stance": "attacker", "node": "attacker"}],
    }
    r = client.post("/scenarios", json={"spec": spec, "id": sid, "overwrite": True})
    assert r.status_code == 200, r.text
    return sid


def test_deploy_blocks_confirmed_missing_image(client, monkeypatch):
    """A docker-local deploy is rejected up front when Docker Hub confidently
    reports a victim image as missing (the hallucinated-image case) — nothing is
    queued, so it can't pull-fail opaquely in the worker."""
    import api
    import image_check

    monkeypatch.setattr(api, "resolve_provider_name", lambda *a, **k: "docker-local")
    monkeypatch.setattr(image_check, "exists_on_hub", lambda ref: False)  # all 404
    sid = _import_container_scenario(client, "blk-missing", "nope/totallyfake:latest")

    resp = client.post(
        "/deploy",
        json={"scenario": sid, "instance_id": "blk-missing", "provider": "docker-local"},
    )
    assert resp.status_code == 422
    assert "not found on Docker Hub" in resp.text
    assert api.deploy_lab.calls == []  # nothing queued


def test_deploy_allows_when_image_exists(client, monkeypatch):
    """When Docker Hub confirms the images exist, the deploy proceeds normally."""
    import api
    import image_check

    monkeypatch.setattr(api, "resolve_provider_name", lambda *a, **k: "docker-local")
    monkeypatch.setattr(image_check, "exists_on_hub", lambda ref: True)  # all present
    sid = _import_container_scenario(client, "blk-ok", "vulnerables/web-dvwa:latest")

    resp = client.post(
        "/deploy",
        json={"scenario": sid, "instance_id": "blk-ok", "provider": "docker-local"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"
    assert api.deploy_lab.calls  # queued


def test_deploy_image_check_skipped_for_non_docker_local(client, monkeypatch):
    """mock/vm resolutions never pull Docker Hub, so the gate must not run (no Hub
    call) even with an image Docker Hub would 404 — no false block off docker-local."""
    import api
    import image_check

    monkeypatch.setattr(api, "resolve_provider_name", lambda *a, **k: "mock")
    calls = {"n": 0}

    def _counting_exists(ref):
        calls["n"] += 1
        return False

    monkeypatch.setattr(image_check, "exists_on_hub", _counting_exists)
    sid = _import_container_scenario(client, "blk-skip", "nope/totallyfake:latest")

    resp = client.post(
        "/deploy",
        json={"scenario": sid, "instance_id": "blk-skip", "provider": "docker-local"},
    )
    assert resp.status_code == 200, resp.text
    assert calls["n"] == 0  # the Docker Hub check was skipped entirely
