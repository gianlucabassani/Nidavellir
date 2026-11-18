"""
F2 (work order 2026-11-18): a ``persistent`` binding survives destroy + redeploy
of the same scenario, so the agent's first call on the new arena is authorised
without a second operator grant. Opt-in and audited; a non-persistent binding,
a revoked one, or another scenario never carries.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import api
import bindings
from auth import generate_api_key, hash_api_key
from database import Database

SCENARIO = "container_web_pentest"


def _client(role, name=None):
    name = name or f"f2-{role}-{uuid.uuid4().hex[:8]}"
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), name, role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    client.name = name
    return client


@pytest.fixture()
def operator(monkeypatch):
    queued = []
    monkeypatch.setattr(api.deploy_lab, "delay", lambda **kw: queued.append(kw))
    monkeypatch.setattr(api.destroy_lab, "delay", lambda *a, **kw: None)
    client = _client("operator")
    client.persistent_agents = []
    yield client
    # Close every lineage this test opened so later deploys of the shared
    # scenario in other modules never inherit a test binding.
    db = Database()
    for arena, agent in client.persistent_agents:
        db.record_event(arena, bindings.BINDING_REVOKE,
                        {"agent_name": agent, "reason": "test_teardown"}, actor="test")
    for dep in db.list_deployments():
        if dep["id"] in client.arenas and dep["status"] in ("pending", "active"):
            if dep["status"] == "pending":
                db.update_deployment(dep["id"], status="deploying")
                db.update_deployment(dep["id"], status="active")
            db.update_deployment(dep["id"], status="destroying")
            db.update_deployment(dep["id"], status="destroyed")


def _deploy(operator, name="f2-arena"):
    response = operator.post("/deploy", json={"scenario": SCENARIO, "instance_id": name})
    assert response.status_code == 200, response.text
    arena = response.json()["instance_id"]
    operator.arenas = getattr(operator, "arenas", set()) | {arena}
    db = Database()
    db.update_deployment(arena, status="deploying")
    db.update_deployment(arena, status="active",
                         outputs={"node_victim_name": f"nv-{arena[:8]}-victim"})
    return arena, response.json()


def _destroy(operator, arena):
    assert operator.delete(f"/destroy/{arena}").status_code == 200
    Database().update_deployment(arena, status="destroyed")


def _bind(operator, arena, agent, *, persistent, stance="attacker"):
    response = operator.post(f"/arenas/{arena}/bindings", json={
        "agent_name": agent.name, "stance": stance, "persistent": persistent})
    assert response.status_code == 200, response.text
    assert response.json()["persistent"] is persistent
    if persistent:
        operator.persistent_agents.append((arena, agent.name))


def test_persistent_binding_survives_destroy_and_redeploy(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=True)
    _destroy(operator, first)

    second, body = _deploy(operator)
    assert agent.name in body["carried_over_bindings"]
    # The agent's first call is authorised without operator action.
    assert agent.get(f"/status/{second}").status_code == 200
    finding = agent.post(f"/arenas/{second}/findings", json={"title": "after redeploy"})
    assert finding.status_code == 200, finding.text

    db = Database()
    audit = db.list_events(second, types=(bindings.BINDING_CARRIED_OVER,))
    assert len(audit) == 1
    assert audit[0]["payload"]["previous_instance_id"] == first
    assert audit[0]["payload"]["agent_name"] == agent.name
    grant = bindings.binding_for(
        db.list_events(second, types=bindings.BINDING_EVENT_TYPES), agent.name)
    assert grant["stance"] == "attacker" and grant["persistent"]
    assert grant["carried_over_from"] == first
    # Stance still applies: an attacker carried over cannot configure.
    assert agent.post(f"/arenas/{second}/extend", json={"seconds": 600}).status_code == 403
    # Agents never see the audit event (bindings are operator material).
    visible = agent.get(f"/deployments/{second}/events").json()["events"]
    assert visible  # created/status are visible
    assert not any("binding" in e["type"] for e in visible)


def test_non_persistent_binding_is_still_refused_after_redeploy(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=False)
    _destroy(operator, first)
    second, body = _deploy(operator)
    assert agent.name not in body["carried_over_bindings"]
    assert agent.get(f"/status/{second}").status_code == 403
    assert agent.post(f"/arenas/{second}/findings", json={"title": "x"}).status_code == 403


def test_default_grant_is_not_persistent(operator):
    agent = _client("agent")
    arena, _ = _deploy(operator)
    response = operator.post(f"/arenas/{arena}/bindings", json={"agent_name": agent.name})
    assert response.json()["persistent"] is False


def test_revoked_binding_never_carries_over(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=True)
    assert operator.delete(f"/arenas/{first}/bindings/{agent.name}").json()["revoked"]
    _destroy(operator, first)
    second, body = _deploy(operator)
    assert agent.name not in body["carried_over_bindings"]
    assert agent.get(f"/status/{second}").status_code == 403


def test_revoke_on_a_carried_arena_ends_the_chain(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=True)
    _destroy(operator, first)
    second, _ = _deploy(operator)
    assert agent.get(f"/status/{second}").status_code == 200
    operator.delete(f"/arenas/{second}/bindings/{agent.name}")
    _destroy(operator, second)
    # The persistent grant on `first` is older than the revoke on `second`.
    third, body = _deploy(operator)
    assert agent.name not in body["carried_over_bindings"]
    assert agent.get(f"/status/{third}").status_code == 403


def test_non_persistent_regrant_downgrades_carry_over(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=True)
    _bind(operator, first, agent, persistent=False)
    _destroy(operator, first)
    second, _ = _deploy(operator)
    assert agent.get(f"/status/{second}").status_code == 403


def test_pause_travels_with_the_carried_binding(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=True)
    operator.post(f"/arenas/{first}/bindings/{agent.name}/pause")
    _destroy(operator, first)
    second, _ = _deploy(operator)
    assert agent.get(f"/status/{second}").status_code == 200  # reads allowed
    assert agent.post(f"/arenas/{second}/findings", json={"title": "x"}).status_code == 423


def test_another_scenario_never_inherits(operator):
    agent = _client("agent")
    first, _ = _deploy(operator)
    _bind(operator, first, agent, persistent=True)
    other = str(uuid.uuid4())
    Database().create_deployment(other, "f2-other", "some_other_scenario", provider="mock")
    operator.arenas = operator.arenas | {other}
    assert api._carry_over_bindings(other, "some_other_scenario") == []


def test_carry_over_candidates_newest_decision_wins():
    def ev(i, lab, kind, agent, **payload):
        return {"id": i, "lab_id": lab, "type": kind,
                "payload": {"agent_name": agent, **payload}}

    events = [  # newest first
        ev(6, "a2", bindings.BINDING_REVOKE, "x"),
        ev(5, "a1", bindings.BINDING_GRANT, "y", stance="attacker", persistent=True),
        ev(4, "a1", bindings.BINDING_GRANT, "x", stance="attacker", persistent=True),
        ev(3, "a1", bindings.BINDING_GRANT, "z", stance=None, persistent=False),
    ]
    carried = bindings.carry_over_candidates(events)
    assert [(c["agent_name"], c["previous_instance_id"]) for c in carried] == [("y", "a1")]
