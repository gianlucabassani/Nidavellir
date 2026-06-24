"""
Agent-session telemetry: `POST /arenas/{id}/agent-session` records the connected
BYO agent's model + provider as an append-only `agent_session` event. This is
self-declared attribution (Nidavellir ships no AI) that powers the operator
console's connected-model indicator.
"""
from fastapi.testclient import TestClient


def _client(role="agent"):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=f"{role}-session", role=role)
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.db = Database()
    return c


def _arena(db, iid, scenario="container_web_pentest"):
    db.create_deployment(iid, iid, scenario, provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(
        iid, status="active", outputs={"node_victim_name": "nv-x-victim"}, actor="test"
    )
    return iid


def test_announce_records_an_agent_session_event():
    c = _client("agent")  # the BYO agent itself announces (agent role is enough)
    iid = _arena(c.db, "as-arena-1")
    resp = c.post(
        f"/arenas/{iid}/agent-session",
        json={"model": "claude-opus-4-8", "provider": "anthropic", "stance": "attacker"},
    )
    assert resp.status_code == 200 and resp.json()["recorded"] is True

    sessions = [e for e in c.db.list_events(lab_id=iid) if e["type"] == "agent_session"]
    assert sessions, "expected an agent_session event"
    payload = sessions[0]["payload"]
    assert payload["model"] == "claude-opus-4-8"
    assert payload["provider"] == "anthropic"
    assert payload["stance"] == "attacker"


def test_announce_unknown_arena_is_404():
    c = _client("agent")
    resp = c.post("/arenas/does-not-exist/agent-session",
                  json={"model": "m", "provider": "p"})
    assert resp.status_code == 404


def test_announce_requires_model_and_provider():
    c = _client("agent")
    iid = _arena(c.db, "as-arena-2")
    assert c.post(f"/arenas/{iid}/agent-session", json={"model": "m"}).status_code == 422
    assert c.post(f"/arenas/{iid}/agent-session", json={"provider": "p"}).status_code == 422
