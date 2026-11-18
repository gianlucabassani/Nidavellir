"""Shared helpers for the research integrity layer tests (R1–R4)."""
import uuid

from fastapi.testclient import TestClient


def client(role: str):
    import api
    import auth
    from database import Database

    name = f"ri-{role}-{uuid.uuid4().hex[:8]}"
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name, role=role)
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.name = name
    return c


def active_arena(scenario: str = "custom") -> str:
    from database import Database

    db = Database()
    arena = uuid.uuid4().hex[:16]
    db.create_deployment(arena, arena, scenario, provider=None, actor="test")
    db.update_deployment(arena, status="deploying", actor="test")
    db.update_deployment(arena, status="active",
                         outputs={"node_victim_name": "nv-victim"}, actor="test")
    return arena


def bind(operator, arena: str, agent, stance: str | None = None) -> None:
    r = operator.post(f"/arenas/{arena}/bindings",
                      json={"agent_name": agent.name, "stance": stance})
    assert r.status_code == 200, r.text


def research_mode(operator, arena: str, enabled: bool = True) -> None:
    r = operator.post(f"/arenas/{arena}/research-mode",
                      json={"enabled": enabled, "reason": "test"})
    assert r.status_code == 200, r.text


def contract(**overrides) -> dict:
    body = {
        "id": f"H-{uuid.uuid4().hex[:6]}",
        "source": "fix-diff",
        "provenance": "commit 1a2b3c4 (fix: check owner before delete)",
        "preconditions": ["authenticated low-privilege user"],
        "invariant": "only the owner may delete a resource",
        "source_sink": {"source": "DELETE /api/item/{id}", "sink": "ItemStore.delete"},
        "expected_observable": "204 and the victim's item is gone",
        "negative_control": "same request on the fixed build returns 403",
        "dedup_key": "item-delete-missing-owner-check",
        "probe_budget": 2,
        "stop_condition": "two consistent 403s on the vulnerable build",
    }
    body.update(overrides)
    return body
