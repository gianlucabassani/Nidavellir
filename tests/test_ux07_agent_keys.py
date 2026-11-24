"""UX-07: connect an agent from the console.

An operator mints a role=agent key bound to one arena in one stance; the key is
shown once and only its digest is stored. The key keeps FR-04 rules: it reaches
only the arena it is bound to and never has operator authority. The console
reads whether the agent has connected from its first ``agent_session``.
"""
import uuid

from fastapi.testclient import TestClient

from tests.research_support import active_arena, client


def _name():
    return f"ux07-{uuid.uuid4().hex[:8]}"


def _as(key):
    import api

    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


def test_operator_mints_a_bound_agent_key_shown_once():
    operator = client("operator")
    arena = active_arena()
    name = _name()
    r = operator.post(f"/arenas/{arena}/agent-keys", json={"name": name, "stance": "attacker"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "agent" and body["api_key"].startswith("cg_")

    from database import Database
    keys = Database().api_keys_by_name(name)
    assert len(keys) == 1 and keys[0]["role"] == "agent"
    assert body["api_key"] not in str(keys)

    bound = operator.get(f"/arenas/{arena}/bindings").json()["bindings"]
    assert {"agent_name": name, "stance": "attacker"}.items() <= next(
        b for b in bound if b["agent_name"] == name).items()

    events = operator.get(f"/deployments/{arena}/events?limit=20").json()["events"]
    assert body["api_key"] not in str(events)
    assert any(e["type"] == "agent_key_created" for e in events)


def test_the_new_key_keeps_fr04_scope():
    operator = client("operator")
    arena, other = active_arena(), active_arena()
    key = operator.post(f"/arenas/{arena}/agent-keys",
                        json={"name": _name(), "stance": "attacker"}).json()["api_key"]
    agent = _as(key)
    assert agent.get(f"/status/{arena}").status_code == 200
    assert agent.get(f"/status/{other}").status_code == 403
    assert agent.post(f"/arenas/{other}/agent-keys",
                      json={"name": _name(), "stance": "attacker"}).status_code == 403
    assert agent.get("/deployments").status_code == 403


def test_agents_cannot_mint_and_names_and_states_are_checked():
    operator = client("operator")
    agent = client("agent")
    arena = active_arena()
    assert agent.post(f"/arenas/{arena}/agent-keys",
                      json={"name": _name(), "stance": "attacker"}).status_code == 403
    taken = _name()
    assert operator.post(f"/arenas/{arena}/agent-keys",
                         json={"name": taken, "stance": "defender"}).status_code == 201
    assert operator.post(f"/arenas/{arena}/agent-keys",
                         json={"name": taken, "stance": "defender"}).status_code == 409
    assert operator.post(f"/arenas/{arena}/agent-keys",
                         json={"name": agent.name, "stance": "attacker"}).status_code == 409
    for bad in ({"name": "bad name", "stance": "attacker"},
                {"name": _name(), "stance": "root"},
                {"name": _name(), "stance": "attacker", "role": "admin"}):
        assert operator.post(f"/arenas/{arena}/agent-keys", json=bad).status_code == 422
    assert operator.post("/arenas/missing/agent-keys",
                         json={"name": _name(), "stance": "attacker"}).status_code == 404

    from database import Database
    db = Database()
    db.update_deployment(arena, status="destroying", actor="test")
    assert operator.post(f"/arenas/{arena}/agent-keys",
                         json={"name": _name(), "stance": "attacker"}).status_code == 409


def test_connection_status_waits_then_reports_the_first_session():
    operator = client("operator")
    arena = active_arena()
    name = _name()
    key = operator.post(f"/arenas/{arena}/agent-keys",
                        json={"name": name, "stance": "attacker"}).json()["api_key"]
    status = operator.get(f"/arenas/{arena}/agent-connection/{name}").json()
    assert status["bound"] and not status["connected"] and status["key"]["last_used_at"] is None

    r = _as(key).post(f"/arenas/{arena}/agent-session",
                      json={"model": "some-model", "provider": "some-provider"})
    assert r.status_code == 200, r.text
    status = operator.get(f"/arenas/{arena}/agent-connection/{name}").json()
    assert status["connected"] and status["session"]["model"] == "some-model"
    assert status["key"]["last_used_at"]
    assert client("agent").get(f"/arenas/{arena}/agent-connection/{name}").status_code == 403
