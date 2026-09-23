"""REST authorization and budget behavior shared by console and MCP callers."""
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

import api
from auth import generate_api_key, hash_api_key
from database import Database


def _client(role):
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), f"budget-{role}-{uuid.uuid4().hex[:8]}", role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return client


def _active():
    arena = str(uuid.uuid4())
    db = Database()
    db.create_deployment(arena, arena, "custom", provider="mock",
                         expires_at=datetime.now() + timedelta(hours=1))
    db.update_deployment(arena, status="deploying")
    db.update_deployment(arena, status="active", outputs={"node_victim_name": "mock-victim"})
    return arena


def test_direct_rest_budget_stop_and_agent_authorization():
    admin, agent = _client("admin"), _client("agent")
    arena = _active()
    assert agent.get(f"/arenas/{arena}/budget").status_code == 403
    assert agent.post(f"/arenas/{arena}/stop", json={
        "reason": "forbidden", "idempotency_key": uuid.uuid4().hex,
    }).status_code == 403
    assert admin.post(f"/arenas/{arena}/stop", json={
        "reason": "test stop", "idempotency_key": uuid.uuid4().hex,
    }).status_code == 200
    assert admin.get(f"/arenas/{arena}/budget").json()["arena"]["state"] == "stopped"
    assert admin.post(f"/arenas/{arena}/exec", json={"node": "victim", "command": "id"}).status_code == 423
    assert admin.post(f"/arenas/{arena}/resume", json={
        "reason": "verified", "idempotency_key": uuid.uuid4().hex,
    }).status_code == 200
    assert agent.post("/system/emergency-stop", json={
        "reason": "forbidden", "idempotency_key": uuid.uuid4().hex,
    }).status_code == 403


def test_direct_rest_spends_one_action_and_rejects_token_cap():
    admin = _client("admin")
    arena = _active()
    Database().revise_budget_policy(
        arena, action_cap=1, deadline=datetime.now() + timedelta(minutes=30),
        actor="operator", reason="single action",
    )
    command = {"node": "victim", "command": "id"}
    assert admin.post(f"/arenas/{arena}/exec", json=command).status_code == 200
    assert admin.post(f"/arenas/{arena}/exec", json=command).status_code == 429
    assert admin.get(f"/arenas/{arena}/budget").json()["policy"]["spent"] == 1
    unsupported = admin.post("/deploy", json={
        "scenario": "basic_pentest", "instance_id": f"token-{uuid.uuid4().hex[:8]}",
        "token_budget": 100,
    })
    assert unsupported.status_code == 422
    assert admin.post(f"/arenas/{arena}/poc-jobs", json={
        "source": "print('never runs')", "idempotency_key": uuid.uuid4().hex,
        "cost_budget_usd": 0.10,
    }).status_code == 422
