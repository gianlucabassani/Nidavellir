"""
Tests for per-request provider selection (ADR-0003 follow-up).

Pins: the optional `provider` field on /deploy (existence + infra-class
compatibility checks), GET /providers, the provider being recorded on the
deployment and threaded to the deploy task, and destroy resolving the
recorded provider.
"""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from database import Database  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402


class _FakeTask:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return None


@pytest.fixture()
def client(monkeypatch):
    import api

    fake = _FakeTask()
    monkeypatch.setattr(api, "deploy_lab", fake)
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="psel-tests", role="admin")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.fake_deploy = fake
    return c


def test_providers_endpoint_lists_backends(client):
    resp = client.get("/providers")
    assert resp.status_code == 200
    by_name = {p["name"]: p["infra_class"] for p in resp.json()["providers"]}
    assert by_name == {
        "mock": "any",
        "openstack": "vm",
        "docker-local": "container",
        "aws": "vm",
    }


def test_deploy_without_provider_uses_default(client):
    resp = client.post(
        "/deploy", json={"scenario": "basic_pentest", "instance_id": "psel-default"}
    )
    assert resp.status_code == 200
    (_, kwargs), = client.fake_deploy.calls
    assert kwargs["provider"] is None


def test_compatible_provider_recorded_and_threaded(client):
    resp = client.post(
        "/deploy",
        json={
            "scenario": "container_web_pentest",
            "instance_id": "psel-docker",
            "provider": "docker-local",
        },
    )
    assert resp.status_code == 200
    system_id = resp.json()["instance_id"]

    (_, kwargs), = client.fake_deploy.calls
    assert kwargs["provider"] == "docker-local"
    assert Database().get_deployment(system_id)["provider"] == "docker-local"


def test_vm_scenario_on_container_provider_rejected(client):
    resp = client.post(
        "/deploy",
        json={
            "scenario": "basic_pentest",       # requires vm
            "instance_id": "psel-bad",
            "provider": "docker-local",        # provides container
        },
    )
    assert resp.status_code == 422
    assert "vm-class" in resp.text
    assert client.fake_deploy.calls == []


def test_vm_scenario_without_provider_rejected_when_default_is_container(
    client, monkeypatch
):
    """No explicit provider resolves to the active default; a vm-scenario must
    still be rejected up front when that default is container-class (was a
    silent bypass → async Celery failure)."""
    # MOCK_MODE (on by default in the suite) would override RANGE_PROVIDER to
    # the any-class mock provider; turn it off so docker-local is the default.
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("RANGE_PROVIDER", "docker-local")  # default → container
    resp = client.post(
        "/deploy",
        json={"scenario": "basic_pentest", "instance_id": "psel-nodef"},  # vm
    )
    assert resp.status_code == 422
    assert "vm-class" in resp.text
    assert client.fake_deploy.calls == []


def test_container_scenario_on_vm_provider_rejected(client):
    resp = client.post(
        "/deploy",
        json={
            "scenario": "container_web_pentest",
            "instance_id": "psel-bad2",
            "provider": "openstack",
        },
    )
    assert resp.status_code == 422
    assert client.fake_deploy.calls == []


def test_mock_provider_accepts_any_scenario(client):
    for scenario in ("basic_pentest", "container_web_pentest"):
        resp = client.post(
            "/deploy",
            json={"scenario": scenario, "instance_id": "psel-mock", "provider": "mock"},
        )
        assert resp.status_code == 200, scenario


def test_unknown_provider_rejected(client):
    resp = client.post(
        "/deploy",
        json={"scenario": "basic_pentest", "instance_id": "psel-x", "provider": "ghost"},
    )
    assert resp.status_code == 422
    assert "GET /providers" in resp.text


def test_orchestrator_resolves_provider_by_name(monkeypatch):
    # Registry name→driver resolution (the real-backend path); MOCK_MODE (on by
    # default in the suite) would otherwise force every name to the mock driver.
    monkeypatch.setenv("MOCK_MODE", "false")
    assert Orchestrator(provider_name="docker-local").provider.name == "docker-local"
    assert Orchestrator(provider_name="mock").provider.name == "mock"


def test_destroy_task_uses_recorded_provider(monkeypatch):
    """destroy_lab must build its Orchestrator from the deployment's provider."""
    import tasks

    db = Database()
    db.create_deployment("psel-destroy-1", "lab", "container_web_pentest",
                         provider="docker-local")

    seen = {}

    class _SpyOrchestrator:
        def __init__(self, provider=None, provider_name=None):
            seen["provider_name"] = provider_name

        def destroy(self, instance_id):
            return {"success": True}

    monkeypatch.setattr(tasks, "Orchestrator", _SpyOrchestrator)
    tasks.destroy_lab("psel-destroy-1")

    assert seen["provider_name"] == "docker-local"
