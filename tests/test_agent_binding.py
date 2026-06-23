"""
Server-enforced agent ↔ arena binding (ROADMAP §2.1 D1 / ADR-0005).

The orchestrator — not just the gateway — gates whether an `agent` key may DRIVE
an arena (exec / report findings / configure the victim), and in what stance.
Operators/admins manage every arena and bypass the check. Bindings are granted
three ways: auto on agent self-deploy (own sandbox), an operator grant, or named
at setup/start (configurator, revoked at finish).
"""
import pytest
from fastapi.testclient import TestClient


def _client(role, name):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name, role=role)
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.db = Database()
    c.principal_name = name
    return c


@pytest.fixture()
def operator():
    return _client("operator", "binding-op")


@pytest.fixture()
def agent():
    return _client("agent", "binder-agent")


def _active_arena(db, iid, outputs=None):
    db.create_deployment(iid, iid, "custom", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(
        iid, status="active",
        outputs=outputs or {"node_victim_name": "cg-victim"}, actor="test",
    )
    return iid


# --- exec: the core key↔arena gate ------------------------------------------


def test_unbound_agent_cannot_exec(operator, agent):
    _active_arena(operator.db, "bind-exec-1")
    r = agent.post("/arenas/bind-exec-1/exec", json={"node": "victim", "command": "id"})
    assert r.status_code == 403
    assert "not bound" in r.text


def test_operator_bypasses_binding(operator):
    _active_arena(operator.db, "bind-exec-op")
    r = operator.post("/arenas/bind-exec-op/exec", json={"node": "victim", "command": "id"})
    assert r.status_code == 200, r.text


def test_operator_grant_lets_agent_exec(operator, agent):
    _active_arena(operator.db, "bind-exec-2")
    g = operator.post("/arenas/bind-exec-2/bindings", json={"agent_name": "binder-agent"})
    assert g.status_code == 200 and g.json()["bound"] is True
    r = agent.post("/arenas/bind-exec-2/exec", json={"node": "victim", "command": "id"})
    assert r.status_code == 200, r.text


def test_binding_is_per_arena(operator, agent):
    _active_arena(operator.db, "bind-A")
    _active_arena(operator.db, "bind-B")
    operator.post("/arenas/bind-A/bindings", json={"agent_name": "binder-agent"})
    # bound to A only
    assert agent.post("/arenas/bind-A/exec", json={"node": "victim", "command": "id"}).status_code == 200
    assert agent.post("/arenas/bind-B/exec", json={"node": "victim", "command": "id"}).status_code == 403


def test_revoke_blocks_the_agent(operator, agent):
    _active_arena(operator.db, "bind-revoke")
    operator.post("/arenas/bind-revoke/bindings", json={"agent_name": "binder-agent"})
    assert agent.post("/arenas/bind-revoke/exec", json={"node": "victim", "command": "id"}).status_code == 200
    rev = operator.delete("/arenas/bind-revoke/bindings/binder-agent")
    assert rev.status_code == 200 and rev.json()["revoked"] is True
    assert agent.post("/arenas/bind-revoke/exec", json={"node": "victim", "command": "id"}).status_code == 403


# --- stance node-scope (server-side, was gateway-only) -----------------------


def test_attacker_binding_is_foothold_scoped(operator, agent):
    # kali has a shell command → it's the foothold; victim is a target.
    _active_arena(operator.db, "bind-foothold", outputs={
        "node_victim_name": "cg-victim",
        "node_kali_name": "cg-kali",
        "node_kali_ssh_command": "docker exec -it cg-kali bash",
    })
    operator.post("/arenas/bind-foothold/bindings",
                  json={"agent_name": "binder-agent", "stance": "attacker"})
    # exec on the foothold is allowed
    assert agent.post("/arenas/bind-foothold/exec",
                      json={"node": "kali", "command": "id"}).status_code == 200
    # exec directly on the victim (not a foothold) is refused server-side
    r = agent.post("/arenas/bind-foothold/exec", json={"node": "victim", "command": "id"})
    assert r.status_code == 403 and "foothold" in r.text


def test_unrestricted_binding_can_exec_any_node(operator, agent):
    # A stance=None (own-sandbox) binding is NOT foothold-scoped.
    _active_arena(operator.db, "bind-anynode", outputs={
        "node_victim_name": "cg-victim",
        "node_kali_name": "cg-kali",
        "node_kali_ssh_command": "docker exec -it cg-kali bash",
    })
    operator.post("/arenas/bind-anynode/bindings", json={"agent_name": "binder-agent"})
    assert agent.post("/arenas/bind-anynode/exec",
                      json={"node": "victim", "command": "id"}).status_code == 200


# --- self-deploy auto-bind ---------------------------------------------------


def test_agent_self_deploy_autobinds(agent, monkeypatch):
    # The agent deploys a named scenario under its own key → it is auto-bound to
    # the new arena (claimed at deploy). The Celery dispatch is stubbed (no broker
    # in tests); we assert the binding event rather than driving exec.
    import api
    import bindings

    monkeypatch.setattr(api.deploy_lab, "delay", lambda **kw: None)
    r = agent.post("/deploy", json={"scenario": "container_web_pentest", "instance_id": "selfdep"})
    assert r.status_code == 200, r.text
    iid = r.json()["instance_id"]
    events = agent.db.list_events(iid, types=bindings.BINDING_EVENT_TYPES)
    b = bindings.binding_for(events, "binder-agent")
    assert b is not None and b["stance"] is None and b["auto"] is True


# --- findings ----------------------------------------------------------------


def test_findings_require_binding(operator, agent):
    _active_arena(operator.db, "bind-find")
    assert agent.post("/arenas/bind-find/findings",
                      json={"title": "x", "cwe": "CWE-89", "node": "victim"}).status_code == 403
    operator.post("/arenas/bind-find/bindings", json={"agent_name": "binder-agent"})
    assert agent.post("/arenas/bind-find/findings",
                      json={"title": "x", "cwe": "CWE-89", "node": "victim"}).status_code == 200


# --- configurator: claimed at setup/start, revoked at finish -----------------


def _sut_like_arena(db, iid):
    return _active_arena(db, iid, outputs={
        "node_victim_name": "cg-victim",
        "node_kali_name": "cg-kali",
        "node_kali_ssh_command": "docker exec -it cg-kali bash",
    })


def test_unbound_agent_cannot_propose_setup(operator, agent):
    _sut_like_arena(operator.db, "bind-cfg-unbound")
    operator.post("/arenas/bind-cfg-unbound/setup/start", json={"mode": "hitl"})  # no agent_name
    r = agent.post("/arenas/bind-cfg-unbound/setup/propose",
                   json={"node": "victim", "command": "echo hi"})
    assert r.status_code == 403 and "not bound" in r.text


def test_setup_start_agent_name_grants_then_finish_revokes(operator, agent):
    _sut_like_arena(operator.db, "bind-cfg-grant")
    s = operator.post("/arenas/bind-cfg-grant/setup/start",
                      json={"mode": "hitl", "agent_name": "binder-agent"})
    assert s.status_code == 200
    # the named agent can now drive the configurator
    assert agent.get("/arenas/bind-cfg-grant/setup/brief").status_code == 200
    # finishing the session revokes the configurator capability
    assert operator.post("/arenas/bind-cfg-grant/setup/finish").json()["finished"] is True
    assert agent.get("/arenas/bind-cfg-grant/setup/brief").status_code == 403


def test_attacker_binding_cannot_drive_setup(operator, agent):
    # Stance enforcement: an attacker-bound agent may exec but not configure.
    _sut_like_arena(operator.db, "bind-cfg-wrongstance")
    operator.post("/arenas/bind-cfg-wrongstance/bindings",
                  json={"agent_name": "binder-agent", "stance": "attacker"})
    operator.post("/arenas/bind-cfg-wrongstance/setup/start", json={"mode": "hitl"})
    r = agent.post("/arenas/bind-cfg-wrongstance/setup/propose",
                   json={"node": "victim", "command": "echo hi"})
    assert r.status_code == 403 and "may not" in r.text


# --- binding management is operator-only -------------------------------------


def test_binding_endpoints_are_operator_only(operator, agent):
    _active_arena(operator.db, "bind-authz")
    assert agent.post("/arenas/bind-authz/bindings", json={"agent_name": "x"}).status_code == 403
    assert agent.get("/arenas/bind-authz/bindings").status_code == 403
    assert agent.delete("/arenas/bind-authz/bindings/x").status_code == 403
    # operator sees the (empty) list
    assert operator.get("/arenas/bind-authz/bindings").json()["bindings"] == []


def test_grant_unknown_stance_rejected(operator):
    _active_arena(operator.db, "bind-badstance")
    r = operator.post("/arenas/bind-badstance/bindings",
                      json={"agent_name": "x", "stance": "wizard"})
    assert r.status_code == 422


def test_bindings_listed_for_operator(operator, agent):
    _active_arena(operator.db, "bind-list")
    operator.post("/arenas/bind-list/bindings", json={"agent_name": "binder-agent", "stance": "attacker"})
    listing = operator.get("/arenas/bind-list/bindings").json()["bindings"]
    assert len(listing) == 1
    assert listing[0]["agent_name"] == "binder-agent" and listing[0]["stance"] == "attacker"
