"""NV-09 browser-plan boundary and public calibration provenance."""
from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import api
import auth
from database import Database

ROOT = Path(__file__).resolve().parents[1]


def _operator():
    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name=f"nv09-operator-{uuid.uuid4().hex}",
                      role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return client


def test_browser_plan_requires_bounded_operator_assertion():
    client = _operator()
    plan = [{"tool": "browser_visit", "args": {"node": "target", "path": "/"},
             "expect_dom": "Account A owns an object"}]
    payload = {"name": f"nv09-{uuid.uuid4().hex}", "version": "v1", "plan": plan}
    result = client.post("/agent-builds", json=payload)
    assert result.status_code == 201
    assert result.json()["driver"] == "scripted-mcp/v1"
    assert client.post("/agent-builds", json={**payload, "plan": [
        {**plan[0], "expect_dom": ""}]}).status_code == 422
    assert client.post("/agent-builds", json={**payload, "plan": [
        {**plan[0], "expect_dom": "x" * 201}]}).status_code == 422
    assert client.post("/agent-builds", json={**payload, "plan": [
        {"tool": "http_request", "args": {"path": "/"}, "expect_dom": "x"}
    ]}).status_code == 422


def test_synthetic_spa_cannot_be_registered_as_held_out(monkeypatch):
    client = _operator()
    monkeypatch.setattr(api.db, "get_deployment", lambda _: {
        "status": "active", "effective_provider": "docker-local"})
    monkeypatch.setattr(api.db, "get_lifecycle_recipe", lambda _: {
        "scenario_name": "nv09-spa", "recipe_digest": "sha256:recipe",
        "effective_provider": "docker-local", "runtime_reset": {"status": "eligible"},
        "seed": {"schema": "nidavellir/nv09-spa/v1"},
        "scenario": {"vulnerabilities": [{"validator": "authorization_effect"}]}})
    monkeypatch.setattr(api.db, "list_events", lambda *_, **__: [{"payload": {}}])
    payload = {"name": "spa", "version": "v1", "source_arena_id": "source"}
    assert client.post("/eval-challenges", json={**payload,
        "label": "held-out"}).status_code == 422


def test_joint_manifest_contract_and_single_action_change():
    path = ROOT / "cyber-range/fixtures/nv09-spa/manifest-v1.schema.json"
    schema = json.loads(path.read_text())
    assert schema["$id"] == "nidavellir/bughunt-agentic-slice/v1"
    assert {"target", "builds", "seed", "budget", "healthy_control",
            "participant_change", "target_effects", "provenance"} <= set(schema["required"])
    spec = importlib.util.spec_from_file_location(
        "nv09_live", ROOT / "scripts/verify-nv09-live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    good, bad = module._plan("/objects/B"), module._plan("/protected/B")
    changed = [(i, key) for i, (left, right) in enumerate(zip(good, bad))
               for key in set(left["args"]) | set(right["args"])
               if left["args"].get(key) != right["args"].get(key)]
    assert changed == [(2, "path")]
    page = (ROOT / "cyber-range/fixtures/nv09-spa/index.html").read_text()
    script = (ROOT / "cyber-range/fixtures/nv09-spa/app.js").read_text()
    assert '<script src="/app.js"' in page and "fetch(`/protected/${account}`" in script
