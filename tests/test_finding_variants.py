"""Affected-versus-fixed finding groups (NV-11)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
import auth
from database import Database


@pytest.fixture()
def clients():
    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name="variant-operator", role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return db, client


def _arena(db, name):
    db.create_deployment(name, name, name, provider="docker-local", actor="test")
    db.update_deployment(name, status="deploying", actor="test")
    db.update_deployment(name, status="active", actor="test")
    return name


def _post_manual(operator, arena, title, variant_of=None):
    body = {"title": title, "cwe": "CWE-639", "node": "target"}
    if variant_of:
        body["variant_of"] = variant_of
    return operator.post(f"/arenas/{arena}/findings/manual", json=body)


def _finding_payloads(operator, arena):
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    return {e["payload"]["finding_id"]: e["payload"]
            for e in events if e["type"] == "finding"}


def test_manual_finding_links_variant_and_root(clients):
    db, operator = clients
    arena = _arena(db, "variant-root")
    root = _post_manual(operator, arena, "root claim").json()["finding_id"]
    variant = _post_manual(operator, arena, "variant claim", variant_of=root)
    assert variant.status_code == 200, variant.text
    payloads = _finding_payloads(operator, arena)
    assert payloads[root]["research_key"] == root
    assert payloads[root]["variant_of"] is None
    assert payloads[variant.json()["finding_id"]]["variant_of"] == root
    assert payloads[variant.json()["finding_id"]]["research_key"] == root


def test_unknown_variant_of_is_rejected(clients):
    db, operator = clients
    arena = _arena(db, "variant-unknown")
    assert _post_manual(operator, arena, "x", variant_of="0" * 12).status_code == 422
    assert _post_manual(operator, arena, "x", variant_of="not-a-finding").status_code == 422


def test_find_finding_event_prefers_newest(clients):
    db, _ = clients
    db.record_event("arena-old", "finding", {"finding_id": "abc123abc123", "title": "old"})
    db.record_event("arena-new", "finding", {"finding_id": "abc123abc123", "title": "new"})
    event = api._find_finding_event("abc123abc123")
    assert event["lab_id"] == "arena-new"
    assert event["payload"]["title"] == "new"


def test_variant_reference_succeeds_across_arenas_without_leaking(clients):
    db, operator = clients
    source = _arena(db, "variant-source")
    target = _arena(db, "variant-target")
    root = _post_manual(operator, source, "root claim").json()["finding_id"]
    response = _post_manual(operator, target, "variant claim", variant_of=root)
    assert response.status_code == 200
    assert set(response.json()) == {"recorded", "finding_id", "manual"}
