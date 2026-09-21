"""
API-layer tests using FastAPI's TestClient.

The Celery dispatch (`.delay`) is stubbed so these run with no Redis/worker —
we assert the HTTP contract and the synchronous DB side effects, not the async
provisioning (that belongs in an integration test against a live worker).
"""
import uuid
from datetime import datetime, timedelta

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
    reset_task = _FakeTask()
    monkeypatch.setattr(api, "reset_arena", reset_task)

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="tests", role="admin")

    test_client = TestClient(api.app)
    test_client.headers["X-API-Key"] = key
    test_client.fake_reset = reset_task
    return test_client


def test_list_deployments_ok(client):
    resp = client.get("/deployments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_deploy_accepts_and_persists_pending(client):
    resp = client.post(
        "/deploy",
        json={
            "scenario": "basic_pentest",
            "instance_id": "lab-team-1",
            "engagement_purpose": "benchmark",
            "participant_mode": "agent",
            "engagement_time_box_seconds": 3600,
        },
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
    events = client.get(f"/deployments/{system_id}/events").json()["events"]
    intent = next(event for event in events if event["type"] == "engagement_intent")
    assert intent["payload"] == {
        "schema": "nidavellir.engagement-intent/v1",
        "purpose": "benchmark",
        "source": "challenge",
        "participant_mode": "agent",
        "time_box_seconds": 3600,
        "containment": "provider_enforced",
        "monitoring": "automatic",
        "scoring": "automatic",
    }


def test_deploy_rejects_unknown_engagement_purpose(client):
    response = client.post(
        "/deploy",
        json={
            "scenario": "basic_pentest",
            "instance_id": "bad-purpose",
            "engagement_purpose": "marketing",
        },
    )
    assert response.status_code == 422
    assert "engagement_purpose" in response.text


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


def test_reset_is_operator_only_durable_and_idempotent(client, monkeypatch):
    import api
    import auth
    import lifecycle_manifest
    from database import Database
    from states import LabStatus

    scenario = {
        "schema": "nidavellir/v3",
        "name": "api-reset",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{
            "name": "target", "role": "victim",
            "image": "example/reset@sha256:" + "a" * 64,
            "segments": ["lab"], "ports": [8080],
        }],
    }
    readiness = {
        "type": "http", "node": "target", "port": 8080, "path": "/state",
        "expected_status": 200, "expected_state": {"value": 0},
    }
    expires = datetime.now() + timedelta(hours=1)
    recipe = lifecycle_manifest.build_recipe(
        scenario=scenario, scenario_name="api-reset", requested_provider="docker-local",
        effective_provider="docker-local", expires_at=expires.isoformat(),
        readiness=readiness, seed={"value": 0},
    )
    db = Database()
    db.create_deployment(
        "api-reset-source", "api-reset", "api-reset",
        provider="docker-local", effective_provider="docker-local", expires_at=expires,
    )
    db.transition_deployment("api-reset-source", (LabStatus.PENDING,), LabStatus.DEPLOYING)
    db.transition_deployment("api-reset-source", (LabStatus.DEPLOYING,), LabStatus.ACTIVE)
    db.save_lifecycle_recipe("api-reset-source", recipe)
    monkeypatch.setattr(api, "resolve_provider_name", lambda _name=None: "docker-local")
    grant = client.post(
        "/arenas/api-reset-source/bindings",
        json={"agent_name": "bound-only-to-source", "stance": "attacker"},
    )
    assert grant.status_code == 200

    first = client.post(
        "/arenas/api-reset-source/reset",
        json={"idempotency_key": "stable-reset-key"},
    )
    assert first.status_code == 202, first.text
    second = client.post(
        "/arenas/api-reset-source/reset",
        json={"idempotency_key": "stable-reset-key"},
    )
    assert second.status_code == 202, second.text
    assert second.json()["operation_id"] == first.json()["operation_id"]
    assert second.json()["replacement_id"] == first.json()["replacement_id"]
    assert len(client.fake_reset.calls) == 2
    replacement = db.get_deployment(first.json()["replacement_id"])
    assert replacement["status"] == LabStatus.PENDING
    assert replacement["expires_at"] == str(expires)
    assert len(client.get("/arenas/api-reset-source/bindings").json()["bindings"]) == 1
    assert client.get(
        f"/arenas/{first.json()['replacement_id']}/bindings"
    ).json() == {"bindings": []}

    lifecycle = client.get("/arenas/api-reset-source/lifecycle")
    assert lifecycle.status_code == 200
    assert lifecycle.json()["classification"]["runtime_reset"]["status"] == "eligible"

    agent_key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(agent_key), name="reset-agent", role="agent")
    agent = TestClient(api.app)
    agent.headers["X-API-Key"] = agent_key
    assert agent.get("/arenas/api-reset-source/lifecycle").status_code == 403
    assert agent.post(
        "/arenas/api-reset-source/reset",
        json={"idempotency_key": "agent-reset-key"},
    ).status_code == 403
    # This test stubs Celery, so explicitly close its synthetic in-flight claim
    # rather than leaking it into later reaper tests in the shared test database.
    db.update_reset_operation(first.json()["operation_id"], status="failed", terminal=True)


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
