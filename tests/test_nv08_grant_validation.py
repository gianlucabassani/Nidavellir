"""NV-08 business-logic action/effect/control and truth-boundary tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import auth
import http_transactions
import scenarios
from database import Database


@pytest.fixture()
def clients():
    db = Database()
    users = {}
    for role in ("operator", "agent"):
        key = auth.generate_api_key()
        name = f"nv08-{role}-{uuid.uuid4().hex}"
        db.create_api_key(auth.hash_api_key(key), name=name, role=role)
        client = TestClient(api.app)
        client.headers["X-API-Key"] = key
        users[role] = (client, name)
    return db, users


def _arena(db, agent_name):
    name = f"nv08-grants-{uuid.uuid4().hex}"
    spec = {"schema": "nidavellir/v3", "name": name,
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{"name": "target", "role": "victim", "image": "sha256:" + "a" * 64,
                   "segments": ["lab"], "ports": [8080]}],
        "vulnerabilities": [{"id": "grant-duplicate", "title": "Duplicate grant credit",
            "cwe": "CWE-841", "node": "target", "points": 1,
            "validator": "single_use_grant_effect",
            "validation_config": {"actor": "A", "grant": "grant-A"}}]}
    scenarios.save_scenario(name, spec)
    db.create_deployment(name, name, name, provider="docker-local", actor="test")
    db.update_deployment(name, status="deploying", actor="test")
    db.update_deployment(name, status="active", actor="test")
    api._record_lifecycle_recipe(name, scenario_name=name, scenario_config=spec,
        requested_provider="docker-local",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.record_event(name, "agent_binding", {"agent_name": agent_name, "stance": None},
                    actor="test")
    return name


def _transaction(arena, actor, request_id, path, body="duplicate credited!"):
    return http_transactions.record(arena,
        request={"node": "target", "method": "POST", "path": path, "params": {},
                 "headers": {"X-Request-ID": request_id,
                             "Authorization": "Bearer grant-token-a"}, "body": None},
        response={"status": 200, "body": body}, actor=actor)["digest"]


@pytest.mark.parametrize("before,after,status,credited,expected", [
    (1, 2, 200, True, "confirmed"),
    (1, 1, 409, False, "refuted"),
])
def test_grant_verdict_uses_ledger_and_retains_evidence(
        clients, monkeypatch, before, after, status, credited, expected):
    db, users = clients
    operator, _ = users["operator"]
    agent, actor = users["agent"]
    arena = _arena(db, actor)
    digest = _transaction(arena, actor, "grantrequest123", "/grants/grant-A/redeem-unsafe")
    monkeypatch.setattr(api, "_grant_readback", lambda _record, _node, request_id: {
        "request_id": request_id, "actor": "A", "grant": "grant-A",
        "prior_redemptions": before, "after_redemptions": after,
        "status": status, "duplicate_credited": credited})
    monkeypatch.setattr(api, "_grant_control", lambda *_: {
        "actor": "A", "prior_redemptions": 0, "after_redemptions": 1,
        "status": 200, "control_ok": True})
    response = agent.post(f"/arenas/{arena}/findings", json={
        "title": "claimed second credit", "cwe": "CWE-841", "node": "target",
        "transaction_digests": [digest], "evidence": "persuasive response"})
    assert response.status_code == 200
    assert set(response.json()) == {"recorded", "finding_id"}
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    verdict = next(e["payload"]["validation"] for e in events if e["type"] == "finding")
    assert verdict["verdict"] == expected
    assert verdict["validator_id"] == "single_use_grant_effect"
    assert verdict["action_digest"] == digest
    assert verdict["observation_digest"] and verdict["control_digest"]
    agent_events = agent.get(f"/deployments/{arena}/events").json()["events"]
    assert "validation" not in next(e["payload"] for e in agent_events
                                    if e["type"] == "finding")
    assert agent.get(f"/arenas/{arena}/score").status_code == 403
    score = operator.get(f"/arenas/{arena}/score").json()
    assert score["score"]["value"] == (1.0 if credited else 0.0)
    path = f"/arenas/{arena}/validation-evidence/{verdict['observation_digest']}"
    assert operator.get(path).status_code == 200
    assert agent.get(path).status_code == 403
    db.update_deployment(arena, status="destroying", actor="test")
    db.update_deployment(arena, status="destroyed", actor="test")
    assert operator.get(path).status_code == 200
    assert operator.get(f"/arenas/{arena}/score").json()["score"]["value"] == score[
        "score"]["value"]


def test_grant_control_failure_is_infrastructure_failure(clients, monkeypatch):
    db, users = clients
    operator, _ = users["operator"]
    agent, actor = users["agent"]
    arena = _arena(db, actor)
    digest = _transaction(arena, actor, "controlbad123", "/grants/grant-A/redeem-unsafe")
    monkeypatch.setattr(api, "_grant_readback", lambda _record, _node, request_id: {
        "request_id": request_id, "actor": "A", "grant": "grant-A",
        "prior_redemptions": 1, "after_redemptions": 2,
        "status": 200, "duplicate_credited": True})
    monkeypatch.setattr(api, "_grant_control", lambda *_: {
        "actor": "A", "status": 500, "control_ok": False})
    agent.post(f"/arenas/{arena}/findings", json={
        "title": "claimed second credit", "cwe": "CWE-841", "node": "target",
        "transaction_digests": [digest]})
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    verdict = next(e["payload"]["validation"] for e in events if e["type"] == "finding")
    assert verdict["verdict"] == "infrastructure_failure"
    assert verdict["reason_code"] == "control_failed"


def test_unsupported_grant_claim_is_inconclusive(clients, monkeypatch):
    db, users = clients
    operator, _ = users["operator"]
    agent, actor = users["agent"]
    arena = _arena(db, actor)
    monkeypatch.setattr(api, "_grant_readback", lambda *_: pytest.fail("observer ran"))
    response = agent.post(f"/arenas/{arena}/findings", json={
        "title": "invented duplicate credit", "cwe": "CWE-841", "node": "target",
        "evidence": "the response says credited", "poc": "invented"})
    assert response.status_code == 200
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    verdict = next(e["payload"]["validation"] for e in events if e["type"] == "finding")
    assert verdict["verdict"] == "inconclusive"
    assert verdict["reason_code"] == "missing_action"
    assert operator.get(f"/arenas/{arena}/score").json()["score"]["value"] == 0
