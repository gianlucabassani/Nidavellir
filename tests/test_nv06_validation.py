"""NV-06 API evidence chain and participant truth boundary."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

import api
import auth
import http_transactions
import scenarios
import validation_evidence
from database import Database


@pytest.fixture()
def clients():
    db = Database()
    out = {}
    for role in ("operator", "agent"):
        key = auth.generate_api_key()
        db.create_api_key(auth.hash_api_key(key), name=f"nv06-{role}", role=role)
        client = TestClient(api.app)
        client.headers["X-API-Key"] = key
        out[role] = client
    return db, out["operator"], out["agent"]


def _arena(db, name):
    spec = {
        "schema": "nidavellir/v3", "name": name,
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{"name": "target", "role": "victim", "image": "sha256:" + "a" * 64,
                   "segments": ["lab"], "ports": [8080]}],
        "vulnerabilities": [{
            "id": "authz", "title": "authorization", "cwe": "CWE-639", "node": "target",
            "validator": "authorization_effect",
            "validation_config": {"actor": "A", "owner": "B",
                                  "control_token": "operator-only"},
        }],
    }
    scenarios.save_scenario(name, spec)
    db.create_deployment(name, name, name, provider="docker-local", actor="test")
    db.update_deployment(name, status="deploying", actor="test")
    db.update_deployment(name, status="active", actor="test")
    api._record_lifecycle_recipe(
        name, scenario_name=name, scenario_config=spec, requested_provider="docker-local",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.record_event(name, "agent_binding", {"agent_name": "nv06-agent", "stance": None},
                    actor="test")
    return name


def _transaction(arena, request_id, path, body="persuasive private-B"):
    return http_transactions.record(
        arena,
        request={"node": "target", "method": "GET", "path": path, "params": {},
                 "headers": {"X-Request-ID": request_id,
                             "Authorization": "Bearer token-a-public"}, "body": None},
        response={"status": 200, "body": body}, actor="nv06-agent",
    )["digest"]


@pytest.mark.parametrize("effect,status,expected", [
    (True, 200, "confirmed"), (False, 403, "refuted"), (None, None, "infrastructure_failure"),
])
def test_linked_action_oracle_and_retained_review(clients, monkeypatch, effect, status, expected):
    db, operator, agent = clients
    arena = _arena(db, f"nv06-{expected}")
    digest = _transaction(arena, "request123", "/objects/B")

    def readback(_record, _node, request_id):
        if effect is None:
            raise RuntimeError("observer unavailable")
        return {"request_id": request_id, "actor": "A", "owner": "B",
                "status": status, "unauthorized_disclosure": effect}

    monkeypatch.setattr(api, "_authz_readback", readback)
    monkeypatch.setattr(api, "_authz_control", lambda *_: {
        "actor": "B", "owner": "B", "status": 200, "control_ok": True,
    })
    response = agent.post(f"/arenas/{arena}/findings", json={
        "title": "claimed object read", "cwe": "CWE-639", "node": "target",
        "transaction_digests": [digest],
    })
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"recorded", "finding_id"}
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    finding = next(e["payload"] for e in events if e["type"] == "finding")
    verdict = finding["validation"]
    assert verdict["verdict"] == expected
    assert verdict["action_digest"] == digest
    assert verdict["schema"] == "nidavellir/validation-verdict/v1"
    assert verdict["finding_id"] == response.json()["finding_id"]
    assert verdict["arena_id"] == arena
    assert verdict["validator_version"] == 1
    assert agent.get(f"/arenas/{arena}/score").status_code == 403
    agent_events = agent.get(f"/deployments/{arena}/events").json()["events"]
    assert "validation" not in next(e["payload"] for e in agent_events
                                    if e["type"] == "finding")
    score = operator.get(f"/arenas/{arena}/score").json()
    assert score["score"]["value"] == (1.0 if effect is True else 0.0)
    assert score["score"]["metadata"]["solved"] is (effect is True)

    if effect is True:
        manual_digest = verdict["observation_digest"]
        reviewed = operator.post(
            f"/arenas/{arena}/findings/{response.json()['finding_id']}/verify",
            json={"verdict": "confirmed", "evidence_digest": manual_digest},
        )
        assert reviewed.status_code == 200
        after_review = operator.get(f"/arenas/{arena}/score").json()
        assert after_review["confirmed"] == ["authz"]
        assert after_review["manual_confirmed"] == ["authz"]
        assert after_review["score"]["value"] == score["score"]["value"]

    if verdict["observation_digest"]:
        path = f"/arenas/{arena}/validation-evidence/{verdict['observation_digest']}"
        assert operator.get(path).status_code == 200
        assert agent.get(path).status_code == 403
    db.update_deployment(arena, status="destroying", actor="test")
    db.update_deployment(arena, status="destroyed", actor="test")
    assert operator.get(f"/arenas/{arena}/score").json()["score"]["value"] == score["score"]["value"]
    if verdict["observation_digest"]:
        assert operator.get(path).status_code == 200


def test_unsupported_claim_with_correct_cwe_cannot_confirm(clients):
    db, operator, agent = clients
    arena = _arena(db, "nv06-unsupported")
    changed = {
        "schema": "nidavellir/v3", "name": arena,
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{"name": "target", "role": "victim", "image": "sha256:" + "a" * 64,
                   "segments": ["lab"], "ports": [8080]}],
        "vulnerabilities": [],
    }
    scenarios.save_scenario(arena, changed, overwrite=True)
    response = agent.post(f"/arenas/{arena}/findings", json={
        "title": "persuasive claim", "cwe": "CWE-639", "node": "target",
        "evidence": "private-B", "poc": "invented proof",
    })
    assert response.status_code == 200
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    verdict = next(e["payload"]["validation"] for e in events if e["type"] == "finding")
    assert verdict["verdict"] == "inconclusive"
    assert verdict["reason_code"] == "missing_action"
    score = operator.get(f"/arenas/{arena}/score").json()
    assert score["found"] == ["authz"]  # claim coverage is visible
    assert score["confirmed"] == [] and score["score"]["value"] == 0


def test_private_observation_is_arena_scoped_and_integrity_checked():
    digest = validation_evidence.record("nv06-evidence-a", {"effect": True})
    assert validation_evidence.get("nv06-evidence-a", digest)["effect"] is True
    with pytest.raises(validation_evidence.ValidationEvidenceError):
        validation_evidence.get("nv06-evidence-b", digest)
    validation_evidence._path("nv06-evidence-a", digest).write_bytes(b'{"effect":false}')
    with pytest.raises(validation_evidence.ValidationEvidenceError, match="integrity"):
        validation_evidence.get("nv06-evidence-a", digest)
