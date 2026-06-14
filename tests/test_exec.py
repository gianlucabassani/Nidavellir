"""
Tests for in-arena command execution: the provider exec capability and the
audited POST /arenas/{id}/exec endpoint (ROADMAP Phase 2, attacker stance).
"""
import pytest

from providers.aws import AWSProvider
from providers.mock import MockProvider
from providers.openstack import OpenStackProvider


# --- provider exec -----------------------------------------------------------


def test_mock_exec_returns_canned_output():
    res = MockProvider().exec_in_node("lab-1", "jump", "whoami")
    assert res["success"] is True
    assert res["exit_code"] == 0
    assert "whoami" in res["stdout"]


def test_vm_providers_do_not_support_exec_yet():
    for provider in (OpenStackProvider, AWSProvider):
        with pytest.raises(NotImplementedError):
            provider().exec_in_node("lab-1", "n", "id")


# --- POST /arenas/{id}/exec --------------------------------------------------


@pytest.fixture()
def client():
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="exec-tests", role="agent")

    from fastapi.testclient import TestClient

    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.db = Database()
    return c


def _make_active_arena(db, instance_id="exec-arena", outputs=None):
    db.create_deployment(instance_id, instance_id, "custom", provider=None, actor="test")
    db.update_deployment(instance_id, status="deploying", actor="test")  # legal path
    db.update_deployment(
        instance_id, status="active",
        outputs=outputs or {"node_jump_name": "cg-x-jump"}, actor="test",
    )


def test_exec_runs_and_is_audited(client):
    _make_active_arena(client.db)
    resp = client.post("/arenas/exec-arena/exec", json={"node": "jump", "command": "id"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node"] == "jump"
    assert body["exit_code"] == 0
    assert "id" in body["stdout"]  # mock echoes the command
    # the command is written to the audit trail (feeds the defender stance)
    events = client.db.list_events(lab_id="exec-arena")
    assert any(e["type"] == "agent_exec" for e in events)


def test_exec_unknown_arena_is_404(client):
    resp = client.post("/arenas/nope/exec", json={"node": "jump", "command": "id"})
    assert resp.status_code == 404


def test_exec_on_inactive_arena_is_409(client):
    client.db.create_deployment("pending-arena", "pending-arena", "custom", actor="test")
    resp = client.post("/arenas/pending-arena/exec", json={"node": "jump", "command": "id"})
    assert resp.status_code == 409


def test_exec_unknown_node_is_404(client):
    _make_active_arena(client.db, "node-arena", outputs={"node_jump_name": "cg-x-jump"})
    resp = client.post("/arenas/node-arena/exec", json={"node": "ghost", "command": "id"})
    assert resp.status_code == 404


def test_exec_validates_command_bounds(client):
    _make_active_arena(client.db, "bounds-arena")
    # empty command rejected by the request model (422)
    assert client.post("/arenas/bounds-arena/exec",
                       json={"node": "jump", "command": ""}).status_code == 422
    # out-of-range timeout rejected
    assert client.post("/arenas/bounds-arena/exec",
                       json={"node": "jump", "command": "id", "timeout": 9999}).status_code == 422
