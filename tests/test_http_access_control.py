"""Generic HTTP access-control validator: API dispatch and verdict chain.

Runs the generated target-local probe against a loopback server, so the test
covers config normalization, probe execution and the finding verdict without a
container arena.
"""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import auth
import http_transactions
import scenarios
from database import Database


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        auth_header = self.headers.get("Authorization")
        status, body = 200, b"denied"
        if self.path == "/api/objects/vuln" and auth_header == "Bearer actor":
            body = b"restricted-marker"          # the effect under test
        elif self.path == "/api/objects/vuln" and auth_header == "Bearer owner":
            body = b"restricted-marker"
        elif self.path == "/api/objects/fixed" and auth_header == "Bearer owner":
            body = b"restricted-marker"
        elif self.path == "/api/objects/fixed" and auth_header == "Bearer actor":
            status, body = 403, b"denied"
        elif self.path == "/api/objects/shared" and auth_header == "Bearer actor":
            body = b"shared"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


@pytest.fixture(autouse=True)
def _clean_imported():
    """Leave no imported scenario packs behind for the registry-parity test."""
    import config
    config.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    for path in config.SCENARIOS_DIR.glob("*.yaml"):
        path.unlink()
    yield
    for path in config.SCENARIOS_DIR.glob("*.yaml"):
        path.unlink()


@pytest.fixture()
def server():
    instance = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}"
    finally:
        instance.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def clients():
    db = Database()
    out = {}
    for role in ("operator", "agent"):
        key = auth.generate_api_key()
        db.create_api_key(auth.hash_api_key(key), name=f"acl-{role}", role=role)
        client = TestClient(api.app)
        client.headers["X-API-Key"] = key
        out[role] = client
    return db, out["operator"], out["agent"]


def _arena(db, name, base_url, action_path):
    spec = {
        "schema": "nidavellir/v3", "name": name,
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{"name": "target", "role": "victim", "image": "sha256:" + "a" * 64,
                   "segments": ["lab"], "ports": [8080]}],
        "vulnerabilities": [{
            "id": "acl", "title": "access control", "cwe": "CWE-639", "node": "target",
            "validator": "http_access_control",
            "validation_config": {
                "actor": "B", "owner": "A", "base_url": base_url,
                "actor_headers": {"Authorization": "Bearer actor"},
                "owner_headers": {"Authorization": "Bearer owner"},
                "action": {"method": "GET", "path": action_path},
                "control": {"method": "GET", "path": "/api/objects/shared"},
                "forbidden_marker": "restricted-marker",
            },
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
    db.record_event(name, "agent_binding", {"agent_name": "acl-agent", "stance": None},
                    actor="test")
    return name


def _transaction(arena, path):
    return http_transactions.record(
        arena,
        request={"node": "target", "method": "GET", "path": path, "params": {},
                 "headers": {"Authorization": "Bearer actor"}, "body": None},
        response={"status": 200, "body": "restricted-marker"}, actor="acl-agent",
    )["digest"]


@pytest.mark.parametrize("path,expected", [
    ("/api/objects/vuln", "confirmed"), ("/api/objects/fixed", "refuted"),
])
def test_http_access_control_dispatch_and_verdict(clients, monkeypatch, server,
                                                  path, expected):
    db, operator, agent = clients
    arena = _arena(db, f"acl-{expected}", server, path)
    digest = _transaction(arena, path)

    def local_probe(_record, _node, source, timeout=5):
        completed = subprocess.run([sys.executable, "-c", source], capture_output=True,
                                   text=True, timeout=30, check=True)
        return json.loads(completed.stdout)

    monkeypatch.setattr(api, "_target_local_json", local_probe)
    response = agent.post(f"/arenas/{arena}/findings", json={
        "title": "cross-account read", "cwe": "CWE-639", "node": "target",
        "transaction_digests": [digest],
    })
    assert response.status_code == 200, response.text
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    verdict = next(e["payload"] for e in events if e["type"] == "finding")["validation"]
    assert verdict["verdict"] == expected
    assert verdict["validator_id"] == "http_access_control"
    assert verdict["action_digest"] == digest
    assert verdict["observation_digest"] and verdict["control_digest"]
    evidence = operator.get(
        f"/arenas/{arena}/validation-evidence/{verdict['observation_digest']}")
    assert evidence.status_code == 200
    assert evidence.json()["evidence"]["data"]["marker"] is (expected == "confirmed")
    score = operator.get(f"/arenas/{arena}/score").json()
    assert score["score"]["value"] == (1.0 if expected == "confirmed" else 0.0)
    db.update_deployment(arena, status="destroying", actor="test")
    db.update_deployment(arena, status="destroyed", actor="test")
    assert operator.get(
        f"/arenas/{arena}/validation-evidence/{verdict['observation_digest']}"
    ).status_code == 200


def test_variant_group_disappeared_under_controls(clients, monkeypatch, server):
    db, operator, agent = clients

    def local_probe(_record, _node, source, timeout=5):
        completed = subprocess.run([sys.executable, "-c", source], capture_output=True,
                                   text=True, timeout=30, check=True)
        return json.loads(completed.stdout)

    monkeypatch.setattr(api, "_target_local_json", local_probe)
    arenas = {}
    for side, path in (("vuln", "/api/objects/vuln"), ("fixed", "/api/objects/fixed")):
        arenas[side] = _arena(db, f"acl-e2e-{side}", server, path)

    def report(side, variant_of=None):
        digest = _transaction(arenas[side], f"/api/objects/{side}")
        body = {"title": "cross-account read", "cwe": "CWE-639", "node": "target",
                "transaction_digests": [digest]}
        if variant_of:
            body["variant_of"] = variant_of
        response = agent.post(f"/arenas/{arenas[side]}/findings", json=body)
        assert response.status_code == 200, response.text
        return response.json()["finding_id"]

    root = report("vuln")
    report("fixed", variant_of=root)
    group = operator.get(f"/findings/{root}").json()
    assert group["comparison"]["outcome"] == "disappeared_under_controls"
    assert len(group["members"]) == 2
    assert all(member["identity"]["known"] for member in group["members"])
    assert [member["verdict"]["verdict"] for member in group["members"]] == \
        ["confirmed", "refuted"]
