"""OCI target preview/deploy integration and immutable session provenance."""
import pytest
from fastapi.testclient import TestClient

import catalog
from scenario_spec import normalized_nodes


_DIGEST = "sha256:" + "c" * 64
_RUNTIME_REF = f"docker.io/library/nginx@{_DIGEST}"


def _resolved(image):
    return {
        "requested_image": image,
        "registry": "docker.io",
        "repository": "library/nginx",
        "requested_ref": "1.27",
        "resolved_digest": _DIGEST,
        "runtime_ref": _RUNTIME_REF,
    }


@pytest.fixture()
def client(monkeypatch):
    import api
    import auth
    from database import Database

    dispatched = {}

    class _FakeTask:
        def delay(self, *args, **kwargs):
            dispatched.update(kwargs)

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    monkeypatch.setattr(api.oci_intake, "resolve_image", _resolved)
    key = auth.generate_api_key()
    Database().create_api_key(
        auth.hash_api_key(key), name="oci-tests", role="operator"
    )
    test_client = TestClient(api.app)
    test_client.headers["X-API-Key"] = key
    test_client.dispatched = dispatched
    return test_client


def test_build_oci_scenario_preserves_native_startup():
    raw = catalog.build_oci_scenario(
        "oci-target", _RUNTIME_REF, ports=[8080], include_attacker=True
    )
    nodes = normalized_nodes(raw)
    victim = next(node for node in nodes if node["name"] == "sut")
    assert victim["image"] == _RUNTIME_REF
    assert victim["native_startup"] is True
    assert victim["platform"] == "linux/amd64"
    assert victim["command"] is None
    assert {node["name"] for node in nodes} == {"sut", "kali-cli"}


def test_oci_preview_returns_digest_manifest(client):
    response = client.post(
        "/arenas/oci/preview",
        json={
            "instance_id": "oci-preview",
            "image": "nginx:1.27",
            "ports": [80],
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["target_manifest"]["kind"] == "oci"
    assert body["target_manifest"]["resolved_ref"] == _DIGEST
    assert body["target_manifest"]["runtime_ref"] == _RUNTIME_REF
    assert body["target_manifest"]["platform"] == "linux/amd64"


def test_oci_deploy_is_digest_pinned_and_preflight_pending(client):
    from database import Database

    response = client.post(
        "/arenas/oci",
        json={
            "instance_id": "oci-deploy",
            "image": "nginx:1.27",
            "ports": [80],
            "authorization_basis": "public_oss",
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    arena_id = response.json()["instance_id"]
    victim = next(
        node
        for node in normalized_nodes(client.dispatched["scenario_config"])
        if node["name"] == "sut"
    )
    assert victim["image"] == _RUNTIME_REF
    assert victim["native_startup"] is True
    assert victim["platform"] == "linux/amd64"
    prearm = client.dispatched["setup_prearm"]
    assert prearm["open_setup"] is False
    assert prearm["target_manifest"]["resolved_ref"] == _DIGEST

    event = next(
        item
        for item in Database().list_events(arena_id)
        if item["type"] == "session_prearm"
    )
    assert event["payload"]["target"]["runtime_ref"] == _RUNTIME_REF
    pending = client.get(f"/arenas/{arena_id}/preflight")
    assert pending.status_code == 200
    assert pending.json()["target"]["kind"] == "oci"


def test_oci_deploy_requires_authorization(client):
    response = client.post(
        "/arenas/oci",
        json={"instance_id": "oci-no-auth", "image": "nginx:1.27"},
    )
    assert response.status_code == 422
    assert "authorized" in response.text


def test_worker_preflights_oci_but_does_not_open_configurator(monkeypatch):
    import research_session
    import tasks
    from database import Database

    arena_id = "oci-worker"
    database = Database()
    database.create_deployment(
        arena_id, arena_id, "oci:nginx", provider=None, actor="test"
    )

    class _FakeOrchestrator:
        def __init__(self, provider_name=None):
            pass

        def deploy(self, *args, **kwargs):
            return {
                "success": True,
                "outputs": {
                    "node_sut_name": "nv-sut",
                    "node_sut_state": "running",
                },
            }

    setup_opened = []
    monkeypatch.setattr(tasks, "Orchestrator", _FakeOrchestrator)
    monkeypatch.setattr(
        tasks,
        "_open_prearmed_setup",
        lambda *args, **kwargs: setup_opened.append(True),
    )
    manifest = research_session.oci_target_manifest(
        requested_image="nginx:1.27",
        runtime_ref=_RUNTIME_REF,
        resolved_digest=_DIGEST,
        authorization_basis="public_oss",
        authorization_confirmed=True,
        scope_note=None,
        actor="operator",
    )

    tasks.deploy_lab(
        arena_id,
        "oci:nginx",
        "operator",
        setup_prearm={
            "include_attacker": False,
            "auto_build": True,
            "open_setup": False,
            "target_manifest": manifest,
        },
    )

    event = next(
        item
        for item in database.list_events(arena_id)
        if item["type"] == research_session.PREFLIGHT_EVENT
    )
    assert event["payload"]["ready"] is True
    assert event["payload"]["next"] == "engagement"
    assert setup_opened == []
