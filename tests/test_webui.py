"""
WebUI tests: session login (ADR-0002) and CSRF protection (SECURITY #3).

The orchestrator URL points at a closed port so backend calls fail fast and
the routes exercise their offline fallbacks.
"""
import os
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask_wtf")

os.environ.setdefault("ORCHESTRATOR_URL", "http://127.0.0.1:9")  # closed port

_WEBUI = Path(__file__).resolve().parent.parent / "cyber-range" / "webui"
sys.path.insert(0, str(_WEBUI))

from app import app as webui_app  # noqa: E402


@pytest.fixture()
def client():
    webui_app.config["TESTING"] = True
    return webui_app.test_client()


def _csrf_token(client, path="/login"):
    page = client.get(path).data
    match = re.search(rb'name="csrf_token" value="([^"]+)"', page)
    assert match, f"no csrf token rendered on {path}"
    return match.group(1).decode()


def _login(client):
    token = _csrf_token(client)
    return client.post(
        "/login",
        data={"username": "admin", "password": "nidavellir", "csrf_token": token},
    )


def test_console_projections_require_login(client):
    for path in ("/console", "/console/arena/arena-1", "/console/arenas/new",
                 "/console/scenarios", "/console/scenarios/import",
                 "/console/research/new",
                 "/console/benchmark/registry",
                 "/console/activity", "/api/console/activity",
                 "/console/library/targets", "/console/library/agents",
                 "/console/settings", "/console/profile",
                 "/api/console/agents", "/api/console/settings",
                 "/console/evaluations/new",
                 "/console/evaluations/eval-1",
                 "/api/console/evaluations/eval-1", "/api/console/research",
                 "/api/console/benchmark", "/api/console/range",
                 "/api/console/arenas/arena-1"):
        response = client.get(path)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


def test_console_default_switch_keeps_legacy_fallback(client, monkeypatch):
    import app as webui_module

    _login(client)
    monkeypatch.setattr(webui_module, "CONSOLE_DEFAULT", True)
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/console")
    assert client.get("/engagements").status_code == 200
    monkeypatch.setattr(webui_module, "CONSOLE_DEFAULT", False)
    assert client.get("/").status_code == 200


def test_console_benchmark_registry_limits_scope_and_forwards_pinned_records(
    client, monkeypatch,
):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    headers = {"X-CSRFToken": token}
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda path, body: (
        calls.append((path, body)) or {"id": "registered-id"}, 201))

    build = {"name": "probe", "version": "v1", "driver": "scripted-mcp/v1",
             "plan": [{"tool": "get_briefing", "args": {}}], "secret": "do-not-forward"}
    path = "/api/console/benchmark/builds"
    assert client.post(path, json=build).status_code == 400
    assert client.post(path, json=build, headers=headers).status_code == 201
    assert calls[-1] == ("/agent-builds", {key: build[key]
                    for key in ("name", "version", "driver", "plan")})
    assert client.post(path, json={**build, "plan": []}, headers=headers).status_code == 422

    challenge = {"name": "authz", "version": "v1", "source_arena_id": "arena-1",
                 "label": "held-out"}
    path = "/api/console/benchmark/challenges"
    assert client.post(path, json=challenge, headers=headers).status_code == 422
    assert client.post(path, json={**challenge, "label": "calibration"},
                       headers=headers).status_code == 201
    assert calls[-1][0] == "/eval-challenges"
    assert calls[-1][1]["label"] == "calibration"

    suite = {"name": "authz suite", "version": "v1", "challenge_ids": ["c1"],
             "seeds": [1, 2, 3], "action_cap": 100, "deadline_seconds": 600,
             "secret": "do-not-forward"}
    path = "/api/console/benchmark/suites"
    assert client.post(path, json={**suite, "seeds": [True, 2, 3]},
                       headers=headers).status_code == 422
    assert client.post(path, json=suite, headers=headers).status_code == 201
    assert calls[-1] == ("/eval-suites", {key: suite[key] for key in suite
                     if key != "secret"})


def test_console_activity_projects_records_without_private_payload(client, monkeypatch):
    import app as webui_module

    assert _login(client).status_code == 302
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: (None, False))
    assert client.get("/api/console/activity").status_code == 503
    events = [
        {"type": "finding_verification", "lab_id": "arena-1", "ts": "2026-09-28T12:02:00Z",
         "payload": {"finding_id": "f1", "verdict": "confirmed", "private": "hidden-truth"}},
        {"type": "monitor_signal", "lab_id": "arena-1", "ts": "2026-09-28T12:01:00Z",
         "payload": {"kind": "authz", "summary": "Cross-account read", "private": "hidden-truth"}},
        {"type": "finding", "lab_id": "arena-1", "ts": "2026-09-28T12:00:00Z",
         "payload": {"finding_id": "f1", "title": "Cross-account access",
                     "matched_vuln_id": "hidden-truth",
                     "evidence_artifacts": [{"digest": "sha256:abc", "bytes": 12,
                                             "private": "hidden-truth"}]}}
    ]
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: ({"events": events}, True))
    monkeypatch.setattr(webui_module, "_deployments", lambda: ({
        "arena-1": {"user_id": "grant-service"}}, True))
    response = client.get("/api/console/activity")
    assert response.status_code == 200
    data = response.get_json()
    assert data["findings"][0]["verdict"] == "manual_confirmed"
    assert data["artifacts"][0]["digest"] == "sha256:abc"
    assert data["signals"][0]["summary"] == "Cross-account read"
    assert b"hidden-truth" not in response.data


def test_console_shared_projections_and_system_stop_keep_credentials_server_side(
    client, monkeypatch,
):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    payloads = {
        "/agent-builds": {"builds": [{"id": "b1", "name": "probe", "version": "v1",
                                       "driver": "scripted-mcp/v1", "digest": "sha256:abc",
                                       "config": {"private": "secret-plan"}}]},
        "/system/emergency-stop": {"state": "open", "private": "secret-stop"},
        "/agent/model": {"configured": True, "provider": "openai", "model": "test-model",
                         "api_key": "secret-key"},
    }
    monkeypatch.setattr(webui_module, "_api_get", lambda path: (payloads[path], True))
    monkeypatch.setattr(webui_module, "_agent_overview", lambda limit=120: {
        "connections": [], "timeline": []})
    agents = client.get("/api/console/agents")
    settings = client.get("/api/console/settings")
    assert agents.status_code == settings.status_code == 200
    assert agents.get_json()["builds"][0]["digest"] == "sha256:abc"
    assert settings.get_json()["model_connection"]["configured"] is True
    assert b"secret-plan" not in agents.data
    assert b"secret-key" not in settings.data
    assert b"secret-stop" not in settings.data

    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda path, body: (
        calls.append((path, body)) or {"state": "stopped"}, 200))
    path = "/api/console/system-stop"
    assert client.post(path, json={"action": "stop", "reason": "Test"}).status_code == 400
    assert client.post(path, json={"action": "clear", "reason": ""},
                       headers={"X-CSRFToken": token}).status_code == 422
    assert client.post(path, json={"action": "stop", "reason": "Operator safety stop"},
                       headers={"X-CSRFToken": token}).status_code == 200
    assert calls[-1][0] == "/system/emergency-stop"
    assert calls[-1][1]["reason"] == "Operator safety stop"
    assert calls[-1][1]["idempotency_key"]


def test_console_arena_create_validates_catalog_and_uses_docker_local(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    path = "/api/console/arenas"
    body = {"scenario": "container-lab", "instance_id": "new-arena",
            "engagement_purpose": "discovery", "participant_mode": "operator",
            "engagement_time_box_seconds": 3600}
    assert client.post(path, json=body).status_code == 400
    headers = {"X-CSRFToken": token}
    assert client.post(path, json={**body, "instance_id": "../bad"},
                       headers=headers).status_code == 422
    assert client.post(path, json={**body, "engagement_purpose": []},
                       headers=headers).status_code == 422
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: ({"scenarios": [
        {"id": "container-lab", "provider_class": "container"},
        {"id": "vm-lab", "provider_class": "vm"},
    ]}, True))
    assert client.post(path, json={**body, "scenario": "vm-lab"},
                       headers=headers).status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda target, payload: (
        calls.append((target, payload)) or {"instance_id": "arena-uuid"}, 200))
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["instance_id"] == "arena-uuid"
    assert calls == [("/deploy", {**body, "provider": "docker-local"})]


def test_console_research_preview_pins_git_and_launch_hides_service_manifest(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    headers = {"X-CSRFToken": token}
    body = {"target_type": "git", "instance_id": "target-review",
            "repo": "https://github.com/example/project", "ref": "main", "ports": [8080],
            "include_attacker": True, "authorization_basis": "public_oss",
            "authorization_confirmed": True, "scope_note": "Authorized test",
            "engagement_purpose": "research", "participant_mode": "operator",
            "engagement_time_box_seconds": 3600, "setup_mode": "operator",
            "time_box_seconds": 1800, "command_budget": 50, "setup_egress": True}
    assert client.post("/api/console/research/preview", json=body).status_code == 400
    assert client.post("/api/console/research/preview",
                       json={**body, "participant_mode": []},
                       headers=headers).status_code == 422
    calls = []
    commit = "a" * 40

    def api_post(path, payload, timeout=15):
        calls.append((path, payload))
        if path.endswith("preview"):
            return {"valid": True, "target_manifest": {"resolved_ref": commit,
                    "secret": "private-manifest"}, "summary": {"name": "Target", "nodes": 2},
                    "topology": {"nodes": [{"name": "target", "kind": "target",
                                             "role": "victim", "ports": [8080],
                                             "secret": "private-node"}],
                                 "segments": [{"name": "isolated", "nodes": ["target"]}],
                                 "egress": "blocked"},
                    "introspection": {"build_system": "dockerfile",
                                      "private": "secret-introspection"}}, 200
        return {"status": "accepted", "instance_id": "arena-uuid",
                "target_manifest": {"private": "secret-launch"}}, 200

    monkeypatch.setattr(webui_module, "_api_post", api_post)
    preview = client.post("/api/console/research/preview", json=body, headers=headers)
    assert preview.status_code == 200
    assert preview.get_json()["resolved_ref"] == commit
    assert b"secret" not in preview.data
    assert calls[0][0] == "/arenas/sut/preview"
    assert calls[0][1]["provider"] == "docker-local"
    assert client.post("/api/console/research/launch", json=body,
                       headers=headers).status_code == 422
    launch = client.post("/api/console/research/launch", json={**body, "ref": commit},
                         headers=headers)
    assert launch.status_code == 200
    assert launch.get_json()["instance_id"] == "arena-uuid"
    assert b"secret" not in launch.data
    assert calls[-1][0] == "/arenas/sut"
    assert calls[-1][1]["ref"] == commit


def test_console_research_oci_launch_requires_digest(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    body = {"target_type": "oci", "instance_id": "image-review",
            "image": "nginx:1.27", "platform": "linux/amd64", "ports": [80],
            "include_attacker": True, "authorization_basis": "public_oss",
            "authorization_confirmed": True, "engagement_purpose": "research",
            "participant_mode": "operator", "engagement_time_box_seconds": 3600}
    headers = {"X-CSRFToken": token}
    assert client.post("/api/console/research/launch", json=body,
                       headers=headers).status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda path, payload, timeout=15: (
        calls.append((path, payload)) or {"instance_id": "arena-oci", "status": "accepted"}, 200))
    body["image"] = "docker.io/library/nginx@sha256:" + "b" * 64
    result = client.post("/api/console/research/launch", json=body, headers=headers)
    assert result.status_code == 200
    assert calls[0][0] == "/arenas/oci"
    assert calls[0][1]["image"] == body["image"]


def test_console_research_bundle_preview_and_launch_use_digest(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    headers = {"X-CSRFToken": token}
    digest = "sha256:" + "c" * 64
    body = {"target_type": "bundle", "instance_id": "bundle-review",
            "artifact_digest": digest, "ports": [8080], "include_attacker": True,
            "authorization_basis": "owned", "authorization_confirmed": True,
            "engagement_purpose": "research", "participant_mode": "operator",
            "engagement_time_box_seconds": 3600, "setup_mode": "hitl",
            "time_box_seconds": 1800, "command_budget": 50, "setup_egress": False}
    assert client.post("/api/console/research/preview", json=body).status_code == 400
    assert client.post("/api/console/research/preview",
                       json={**body, "artifact_digest": "bad"},
                       headers=headers).status_code == 422
    calls = []

    def api_post(path, payload, timeout=15):
        calls.append((path, payload))
        if path.endswith("preview"):
            return {"valid": True, "target_manifest": {"resolved_ref": digest,
                    "artifact": {"private": "not-for-browser"}},
                    "summary": {"name": "Bundle"}, "topology": {"nodes": []}}, 200
        return {"status": "accepted", "instance_id": "arena-bundle",
                "private": "not-for-browser"}, 200

    monkeypatch.setattr(webui_module, "_api_post", api_post)
    preview = client.post("/api/console/research/preview", json=body, headers=headers)
    assert preview.status_code == 200
    assert preview.get_json()["resolved_ref"] == digest
    assert b"private" not in preview.data
    assert calls[0][0] == "/arenas/source-bundle/preview"
    assert calls[0][1]["artifact_digest"] == digest
    assert calls[0][1]["setup_mode"] == "hitl"
    launch = client.post("/api/console/research/launch", json=body, headers=headers)
    assert launch.status_code == 200
    assert launch.get_json()["instance_id"] == "arena-bundle"
    assert b"private" not in launch.data
    assert calls[-1][0] == "/arenas/source-bundle"


def test_console_setup_projection_reports_outage_and_limits_fields(client, monkeypatch):
    import app as webui_module

    _login(client)
    path = "/api/console/arenas/arena-a/setup"
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: (None, False))
    assert client.get(path).status_code == 503
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: ({
        "open": True, "expired": False, "mode": "hitl", "nodes": ["target"],
        "steps_run": 1, "command_budget": 5, "egress_enforced": False,
        "pending_proposals": [{"step_id": "step-1", "node": "target",
                               "command": "make setup", "rationale": "Build target",
                               "private": "hidden"}],
        "private": "hidden",
    }, True))
    monkeypatch.setattr(webui_module, "_events", lambda _id, limit, type: [{
        "payload": {"mode": "hitl", "time_box_seconds": 900,
                    "command_budget": 5, "setup_egress": True,
                    "artifact": "private"}
    }] if type == "setup_prearm" else [])
    response = client.get(path)
    assert response.status_code == 200
    assert response.get_json()["pending_proposals"][0]["command"] == "make setup"
    assert response.get_json()["planned"] == {
        "mode": "hitl", "time_box_seconds": 900,
        "command_budget": 5, "setup_egress": True,
    }
    assert b"hidden" not in response.data
    monkeypatch.setattr(webui_module, "_events", lambda _id, limit, type: [{
        "payload": {"private": "hidden"}
    }] if type == "setup_finished" else [])
    assert client.get(path).get_json()["finished"] is True


def test_console_browser_visit_rejects_external_paths_and_projects_evidence(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    _login(client)
    path = "/api/console/arenas/a1/browser/visit"
    body = {"node": "target", "path": "/login", "params": {"mode": "test"}, "wait_ms": 500}
    assert client.post(path, json=body).status_code == 400
    for bad in ("https://example.com", "//example.com", "/a?b=1", "/a#b"):
        assert client.post(path, json={**body, "path": bad},
                           headers={"X-CSRFToken": token}).status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda endpoint, payload, timeout=15: (
        calls.append((endpoint, payload, timeout)) or {"node": "target", "success": True,
        "title": "Login", "rendered_dom": "<h1>Login</h1>", "dom_bytes": 14,
        "dom_sha256": "sha256:" + "a" * 64, "truncated": False,
        "url": "http://10.0.0.2/login", "private": "hidden"}, 200))
    response = client.post(path, json=body, headers={"X-CSRFToken": token})
    assert response.status_code == 200
    assert response.get_json()["rendered_dom"] == "<h1>Login</h1>"
    assert b"10.0.0.2" not in response.data and b"hidden" not in response.data
    assert calls == [("/arenas/a1/browser/visit", body, 30)]


def test_console_file_transfer_bounds_csrf_and_projects_chunks(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    _login(client)
    upload = "/api/console/arenas/a1/files/upload"
    download = "/api/console/arenas/a1/files/download"
    headers = {"X-CSRFToken": token}
    assert client.post(upload, json={"path": "input.txt", "content_b64": "YQ=="}).status_code == 400
    assert client.post(upload, json={"path": "input.txt", "content_b64": "a" * 1400000},
                       headers=headers).status_code == 413
    assert client.post(upload, json={"path": "input.txt", "content_b64": 5},
                       headers=headers).status_code == 422
    assert client.post(download, json={"path": "input.txt", "offset": -1, "max_bytes": 1},
                       headers=headers).status_code == 422
    calls = []

    def api_post(path, payload, timeout=15):
        calls.append((path, payload, timeout))
        if path.endswith("upload"):
            return {"uploaded": True, "node": "foothold", "digest": "sha256:" + "b" * 64,
                    "private": "hidden"}, 200
        return {"node": "foothold", "path": "input.txt", "content_b64": "YQ==",
                "offset": 0, "returned_bytes": 1, "file_bytes": 1,
                "next_offset": None, "digest": "sha256:" + "c" * 64,
                "private": "hidden"}, 200

    monkeypatch.setattr(webui_module, "_api_post", api_post)
    response = client.post(upload, json={"path": "input.txt", "content_b64": "YQ==",
                                         "node": "foothold"}, headers=headers)
    assert response.status_code == 200 and response.get_json()["uploaded"]
    assert b"hidden" not in response.data
    response = client.post(download, json={"path": "input.txt", "offset": 0,
                                           "max_bytes": 262144, "node": "foothold"},
                           headers=headers)
    assert response.status_code == 200
    assert response.get_json()["content_b64"] == "YQ=="
    assert b"hidden" not in response.data
    assert calls[0][0] == "/arenas/a1/files/upload"
    assert calls[1][0] == "/arenas/a1/files/download"


def test_console_research_projection_uses_existing_records_without_secrets(client, monkeypatch):
    import app as webui_module

    monkeypatch.setattr(webui_module, "_deployments", lambda: ({
        "arena-1": {"user_id": "grant-service", "status": "active", "scenario": "authz",
                    "expires_at": None, "provider": "docker-local", "api_key": "secret-do-not-emit"},
    }, True))
    monkeypatch.setattr(webui_module, "_all_findings", lambda **_kwargs: [{
        "finding_id": "finding-1", "title": "Cross-account access", "arena_id": "arena-1",
        "arena_name": "grant-service", "arena_known": True, "verdict": "inconclusive",
        "private_truth": "secret-do-not-emit",
    }])
    assert _login(client).status_code == 302
    response = client.get("/api/console/research")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sessions"][0]["name"] == "grant-service"
    assert payload["review"][0]["title"] == "Cross-account access"
    assert b"secret-do-not-emit" not in response.data


def test_console_benchmark_does_not_turn_backend_failure_into_empty_registry(client, monkeypatch):
    import app as webui_module

    monkeypatch.setattr(webui_module, "_api_get", lambda _path: (None, False))
    assert _login(client).status_code == 302
    response = client.get("/api/console/benchmark")
    assert response.status_code == 503
    assert "unavailable" in response.get_json()["error"]


def test_console_arena_projection_keeps_event_payload_out_of_browser(client, monkeypatch):
    import app as webui_module

    def api_get(path, timeout=5):
        if path == "/status/arena-1":
            return {"user_id": "grant-service", "status": "active", "scenario": "authz",
                    "outputs": {"node_researcher_name": "researcher",
                                "node_researcher_ssh_command": "secret-ssh",
                                "node_target_name": "target",
                                "node_target_ports": {"http": 8080}}}, True
        if path.endswith("/budget"):
            return {"policy": {"remaining": 48, "action_cap": 50},
                    "arena": {"state": "open"}}, True
        if path.endswith("/lifecycle"):
            return {"classification": {"runtime_reset": {"status": "eligible",
                                                       "reason": "immutable_recipe"}},
                    "recipe": {"nodes": [
                        {"name": "researcher", "segments": ["lab"], "role": "attacker",
                         "environment_keys": ["SECRET_NAME"]},
                        {"name": "target", "segments": ["lab"], "role": "victim"},
                    ]},
                    "private_recipe": "secret-lifecycle"}, True
        if path.endswith("/poc-jobs"):
            return {"jobs": []}, True
        return None, False

    monkeypatch.setattr(webui_module, "_api_get", api_get)
    monkeypatch.setattr(webui_module, "_events", lambda *args, **kwargs: [{
        "type": "http_transaction", "ts": "2026-09-27T12:00:00Z", "actor": "operator",
        "payload": {"credential": "secret-event"},
    }])
    assert _login(client).status_code == 302
    response = client.get("/api/console/arenas/arena-1")
    assert response.status_code == 200
    assert response.get_json()["budget"]["remaining"] == 48
    assert response.get_json()["nodes"][0]["foothold"] is True
    assert response.get_json()["nodes"][0]["web_capable"] is False
    assert response.get_json()["nodes"][1]["web_capable"] is True
    assert response.get_json()["reset"]["status"] == "eligible"
    assert response.get_json()["topology"] == {"segments": [
        {"name": "lab", "nodes": ["researcher", "target"]}
    ], "unsegmented": []}
    assert b"secret-ssh" not in response.data
    assert b"secret-event" not in response.data
    assert b"secret-lifecycle" not in response.data
    assert b"SECRET_NAME" not in response.data


def test_console_arena_projection_describes_stations_for_testers(client, monkeypatch):
    import app as webui_module

    def api_get(path, timeout=5):
        if path == "/status/arena-1":
            return {"user_id": "grant-service", "status": "active", "scenario": "authz",
                    "outputs": {"node_researcher_name": "researcher",
                                "node_researcher_ssh_command": "secret-ssh",
                                "node_researcher_private_ip": "10.40.0.2",
                                "node_target_name": "target",
                                "node_target_private_ip": "10.40.0.3",
                                "node_target_url": "http://127.0.0.1:18080",
                                "node_target_ports": {"80": 18080}}}, True
        if path.endswith("/lifecycle"):
            return {"classification": {"runtime_reset": {"status": "eligible"}},
                    "recipe": {"nodes": [
                        {"name": "researcher", "segments": ["lab"], "role": "attacker",
                         "image": "kali", "image_pinned": False, "ports": [],
                         "environment_keys": ["SECRET_NAME"]},
                        {"name": "target", "segments": ["lab", "db"], "role": "victim",
                         "image": "dvwa@sha256:abc", "image_pinned": True, "ports": [80]},
                    ]}}, True
        if path.endswith("/capabilities"):
            return {"targets": [{"node": "target", "ready": True, "forward_services": []}],
                    "operations": {
                        "http": {"state": "ready", "reason": "declared_web_target"},
                        "poc": {"state": "unsupported", "reason": "provider_not_implemented"},
                        "token_cost_hard_cap": {"state": "unsupported", "reason": "x"},
                    }}, True
        if path.endswith("/poc-jobs"):
            return {"jobs": []}, True
        return None, False

    monkeypatch.setattr(webui_module, "_api_get", api_get)
    monkeypatch.setattr(webui_module, "_events", lambda *args, **kwargs: [])
    assert _login(client).status_code == 302
    response = client.get("/api/console/arenas/arena-1")
    payload = response.get_json()
    researcher, target = payload["nodes"]
    assert researcher["role"] == "attacker"
    assert researcher["private_ip"] == "10.40.0.2"
    assert researcher["declared_ports"] == []
    assert target["role"] == "victim"
    assert target["image"] == "dvwa@sha256:abc"
    assert target["image_pinned"] is True
    assert target["declared_ports"] == [80]
    assert target["segments"] == ["db", "lab"]
    assert target["url"] == "http://127.0.0.1:18080"
    assert target["ready"] is True
    assert researcher["ready"] is None
    assert payload["capabilities"] == {
        "http": {"state": "ready", "reason": "declared_web_target"},
        "poc": {"state": "unsupported", "reason": "provider_not_implemented"},
    }
    assert b"secret-ssh" not in response.data
    assert b"SECRET_NAME" not in response.data


def test_console_arena_projection_tolerates_missing_capabilities(client, monkeypatch):
    import app as webui_module

    monkeypatch.setattr(webui_module, "_api_get", lambda path, timeout=5: (
        ({"status": "active", "outputs": {"node_target_name": "target"}}, True)
        if path == "/status/arena-1" else (None, False)
    ))
    monkeypatch.setattr(webui_module, "_events", lambda *args, **kwargs: [])
    assert _login(client).status_code == 302
    payload = client.get("/api/console/arenas/arena-1").get_json()
    assert payload["capabilities"] is None
    assert payload["nodes"][0]["role"] is None
    assert payload["nodes"][0]["declared_ports"] == []
    assert payload["nodes"][0]["ready"] is None


def test_console_archived_arena_does_not_claim_nodes_are_running(client, monkeypatch):
    import app as webui_module

    monkeypatch.setattr(webui_module, "_api_get", lambda path, timeout=5: (
        ({"status": "destroyed", "outputs": {"node_target_name": "target",
                                                 "node_target_state": "running"}}, True)
        if path == "/status/arena-1" else ({}, False)
    ))
    monkeypatch.setattr(webui_module, "_events", lambda *args, **kwargs: [])
    assert _login(client).status_code == 302
    payload = client.get("/api/console/arenas/arena-1").get_json()
    assert payload["state"] == "destroyed"
    assert payload["nodes"][0]["state"] == "archived"
    assert payload["topology"] is None


def test_console_findings_projection_excludes_hidden_truth_and_reports_outage(client, monkeypatch):
    import app as webui_module

    assert _login(client).status_code == 302
    path = "/api/console/arenas/arena-1/findings"
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: (None, False))
    assert client.get(path).status_code == 503
    events = [{"type": "finding", "ts": "2026-09-28T10:00:00Z", "payload": {
        "finding_id": "finding-1", "title": "Cross-account access", "cwe": "CWE-639",
        "node": "target", "evidence": "Observed other tenant record", "poc": "GET /records/2",
        "matched_vuln_id": "hidden-truth", "validation": {"confirmed": None,
                         "reason_code": "probe_inconclusive", "private_recipe": "hidden-truth"},
        "evidence_artifacts": [{"digest": "sha256:abc", "bytes": 42, "private": "hidden-truth"}],
    }}]
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: ({"events": events}, True))
    response = client.get(path)
    assert response.status_code == 200
    finding = response.get_json()["findings"][0]
    assert finding["title"] == "Cross-account access"
    assert finding["artifacts"][0]["digest"] == "sha256:abc"
    assert b"hidden-truth" not in response.data


def test_console_evidence_projection_keeps_only_digest_provenance(client, monkeypatch):
    import app as webui_module

    assert _login(client).status_code == 302
    path = "/api/console/arenas/arena-1/evidence"
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: (None, False))
    assert client.get(path).status_code == 503
    events = [
        {"type": "finding", "payload": {"finding_id": "finding-1", "title": "Grant",
         "evidence_artifacts": [{"digest": "sha256:artifact", "bytes": 14,
                                 "raw_bytes": "secret-raw"}],
         "validation": {"observation_digest": "sha256:effect",
                        "private_recipe": "secret-raw"}}},
        {"type": "monitor_signal", "ts": "2026-09-28T10:00:00Z",
         "payload": {"kind": "crash", "node": "target", "severity": "high",
                     "summary": "Worker crashed", "raw_log": "secret-raw"}},
    ]
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: ({"events": events}, True))
    response = client.get(path)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["artifacts"][0]["digest"] == "sha256:artifact"
    assert payload["validations"][0]["digest"] == "sha256:effect"
    assert payload["signals"][0]["kind"] == "crash"
    assert b"secret-raw" not in response.data


def test_console_evaluation_projection_exposes_results_without_private_trial_data(client, monkeypatch):
    import app as webui_module

    record = {
        "id": "eval-1", "state": "completed",
        "comparison": {
            "evidence_scope": "calibration", "leakage_labels": ["calibration"],
            "matched_pairs": 5, "infrastructure_failed_pairs": 0,
            "differences": {"verified": {"mean": -1, "pairs": 5, "interval_status": "degenerate"}},
            "by_challenge": {"challenge-1": {"name": "Grant", "leakage_label": "calibration",
                                               "matched_pairs": 5, "infrastructure_failed_pairs": 0,
                                               "differences": {"verified": {"mean": -1}},
                                               "private_truth": "secret-validator"}},
        },
        "runs": [{"id": "run-1", "side": "baseline", "challenge_id": "challenge-1",
                  "build_id": "build-1", "private_truth": "secret-validator"}],
        "trials": [{"id": "trial-1", "run_id": "run-1", "seed": 1,
                    "state": "completed", "arena_id": "arena-1",
                    "transcript": "secret-validator"},
                   {"id": "trial-2", "run_id": "run-1", "seed": 2,
                    "state": "infrastructure_failure", "arena_id": None,
                    "error": "runner timed out"}],
    }
    monkeypatch.setattr(webui_module, "_api_get", lambda _path, timeout=5: (record, True))
    assert _login(client).status_code == 302
    response = client.get("/api/console/evaluations/eval-1")
    assert response.status_code == 200
    assert response.get_json()["matched_pairs"] == 5
    assert response.get_json()["differences"]["verified"]["mean"] == -1
    assert response.get_json()["progress"] == {"total": 2, "finished": 2, "running": 0}
    assert response.get_json()["trials"][1]["error"] == "runner timed out"
    assert response.get_json()["trials"][0]["side"] == "baseline"
    assert b"secret-validator" not in response.data


def test_console_evaluation_create_validates_input_and_uses_csrf(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    request_body = {"suite_id": "suite-1", "baseline_id": "build-a",
                    "candidate_id": "build-b"}
    assert client.post("/api/console/evaluations", json=request_body).status_code == 400
    headers = {"X-CSRFToken": token}
    bad = client.post("/api/console/evaluations", json={**request_body,
                       "candidate_id": "build-a"}, headers=headers)
    assert bad.status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda path, body: (
        calls.append((path, body)) or {"id": "eval-1"}, 202))
    response = client.post("/api/console/evaluations", json=request_body, headers=headers)
    assert response.status_code == 202
    assert response.get_json()["id"] == "eval-1"
    assert calls == [("/evaluations", request_body)]


def test_console_research_gate_requires_csrf_and_uses_service_authority(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    path = "/api/console/arenas/arena-1/research-gate"
    assert client.post(path, json={"action": "stop"}).status_code == 400
    headers = {"X-CSRFToken": token}
    assert client.post(path, json={"action": "destroy"}, headers=headers).status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda target, body: (
        calls.append((target, body)) or {"state": "stopped"}, 200))
    response = client.post(path, json={"action": "stop", "reason": "Operator confirmed"},
                           headers=headers)
    assert response.status_code == 200
    assert calls[0][0] == "/arenas/arena-1/stop"
    assert calls[0][1]["reason"] == "Operator confirmed"
    assert len(calls[0][1]["idempotency_key"]) == 32


def test_console_lifecycle_reset_and_destroy_use_existing_service_rules(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    path = "/api/console/arenas/arena-1/lifecycle"
    headers = {"X-CSRFToken": token}
    assert client.post(path, json={"action": "reset"}).status_code == 400
    assert client.post(path, json={"action": "archive-delete"},
                       headers=headers).status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda target, payload, timeout=15: (
        calls.append((target, payload)) or {"status": "pending",
                                         "operation_id": "reset-1",
                                         "replacement_id": "arena-2",
                                         "secret": "not-for-browser"}, 202))
    response = client.post(path, json={"action": "reset"}, headers=headers)
    assert response.status_code == 202
    assert response.get_json()["replacement_id"] == "arena-2"
    assert b"not-for-browser" not in response.data
    assert calls[0][0] == "/arenas/arena-1/reset"
    assert calls[0][1]["idempotency_key"].startswith("webui-")
    monkeypatch.setattr(webui_module, "_request_destroy", lambda _id: (True, "Destroy started"))
    response = client.post(path, json={"action": "destroy"}, headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {"status": "accepted"}


def test_routes_require_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_rejects_missing_csrf_token(client):
    resp = client.post("/login", data={"username": "admin", "password": "nidavellir"})
    assert resp.status_code == 400


def test_stop_forms_require_csrf(client):
    _login(client)
    assert client.post("/arena/any-id/stop", data={"reason": "test"}).status_code == 400
    assert client.post("/settings/emergency-stop", data={"reason": "test"}).status_code == 400


def test_login_with_token_and_valid_credentials(client):
    resp = _login(client)
    assert resp.status_code == 302
    assert client.get("/").status_code == 200  # session established


def test_application_shell_groups_navigation_and_global_create(client):
    _login(client)
    html = client.get("/").data.decode()
    nav = html.split('<nav class="nav" aria-label="Primary navigation">', 1)[1]
    nav = nav.split("</nav>", 1)[0]

    for label in (
        "Home", "Engagements", "Evaluations", "Library", "Activity",
        "Administration", "Calibration challenges", "Scenario catalog",
        "Scripted builds", "Suites", "Comparisons", "Agent activity", "Audit trail",
    ):
        assert label in nav
    assert ">Launch<" not in nav
    assert ">SUT<" not in nav

    assert 'id="create-menu"' in html
    assert 'href="/engagements/new"' in html and "New engagement" in html
    for anchor in ("builds", "challenges", "comparisons"):
        assert f'href="/evaluations#{anchor}"' in html
    assert "Available in later roadmap increments" not in html
    assert 'href="/launch"' not in nav and 'href="/wizard"' not in nav
    assert 'id="sidebar-toggle"' in html
    assert 'aria-controls="sidebar"' in html
    assert 'id="sidebar-scrim"' in html and 'aria-label="Close navigation"' in html
    assert html.count('aria-current="page"') == 1


def test_new_engagement_entry_renders_purpose_and_source_choices(client):
    _login(client)
    html = client.get("/engagements/new").data.decode()
    assert 'id="engagement-entry-form"' in html
    for purpose in ("Benchmark", "Discovery", "Calibration", "Manual research"):
        assert purpose in html
    assert 'name="source" value="challenge"' in html
    assert 'name="source" value="target"' in html
    assert 'name="participant_mode" value="operator"' in html
    assert 'name="participant_mode" value="agent"' in html
    assert 'name="participant_mode" value="mixed"' in html
    assert 'name="engagement_time_box_seconds"' in html
    assert "Platform-enforced defaults" in html
    assert html.count('aria-current="page"') == 1


def test_new_engagement_entry_requires_csrf(client):
    _login(client)
    response = client.post(
        "/engagements/new", data={"purpose": "benchmark", "source": "challenge"}
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("source", "expected_path"),
    [("challenge", "/launch"), ("target", "/wizard")],
)
def test_new_engagement_hands_off_to_existing_builder(client, source, expected_path):
    _login(client)
    token = _csrf_token(client, "/engagements/new")
    response = client.post(
        "/engagements/new",
        data={"purpose": "benchmark", "source": source, "csrf_token": token},
    )
    assert response.status_code == 302
    location = response.headers["Location"]
    assert expected_path in location
    assert "purpose=benchmark" in location
    assert "participant_mode=operator" in location
    assert "engagement_time_box_seconds=3600" in location


def test_new_engagement_rejects_unknown_navigation_values(client):
    _login(client)
    token = _csrf_token(client, "/engagements/new")
    response = client.post(
        "/engagements/new",
        data={"purpose": "unknown", "source": "challenge", "csrf_token": token},
    )
    assert response.status_code == 200
    assert b"Choose the engagement purpose" in response.data


def test_builder_shows_selected_engagement_context(client):
    _login(client)
    challenge = client.get("/launch?purpose=benchmark").data.decode()
    target = client.get("/wizard?purpose=discovery").data.decode()
    assert "Engagement setup · 2 of 3" in challenge and "Benchmark" in challenge
    assert "Engagement setup · 2 of 3" in target and "Discovery" in target


def test_challenge_builder_restores_imported_selection_and_purpose(client, monkeypatch):
    import app as webui_module

    monkeypatch.setattr(webui_module, "_catalog", lambda: ([], [], []))
    monkeypatch.setattr(webui_module, "_default_infra", lambda: "container")
    monkeypatch.setattr(
        webui_module,
        "_scenarios",
        lambda: [
            {
                "id": "imported-lab",
                "name": "Imported lab",
                "provider_class": "container",
            }
        ],
    )

    _login(client)
    html = client.get(
        "/launch?purpose=benchmark&scenario=imported-lab"
    ).data.decode()
    assert 'name="engagement_purpose" value="benchmark"' in html
    assert 'value="imported-lab" selected' in html


def test_target_builder_error_preserves_engagement_purpose(client):
    _login(client)
    token = _csrf_token(client, "/wizard?purpose=benchmark")
    response = client.post(
        "/build-sut",
        data={
            "csrf_token": token,
            "engagement_purpose": "benchmark",
            "target_type": "bundle",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/wizard?purpose=benchmark")


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/library/targets", "Targets"),
        ("/administration/providers", "Providers &amp; capacity"),
        ("/administration/security", "Security"),
    ],
)
def test_foundation_destinations_are_clickable_and_honest(client, path, heading):
    _login(client)
    html = client.get(path).data.decode()
    assert heading in html
    assert "Current product boundary" in html
    assert "foundation" in html
    assert html.count('aria-current="page"') == 1


def test_evaluation_and_agent_registry_are_live_console_destinations(client):
    _login(client)
    evaluations = client.get("/evaluations").data.decode()
    agents = client.get("/library/agents").data.decode()
    assert "Run paired evaluation" in evaluations
    assert "Register a scripted agent build" in evaluations
    assert "Agent builds" in agents
    assert "Measure a change, not a claim." in evaluations
    assert "What this proves" in evaluations
    assert "Build versus connection" in agents
    assert 'class="input" id="build-name"' in evaluations
    assert 'class="select" id="compare-suite"' in evaluations
    for anchor in ("builds", "challenges", "suites", "comparisons"):
        assert f'id="{anchor}"' in evaluations
        assert f'href="/evaluations#{anchor}"' in evaluations
    assert "Overview</span><span class=\"tag\">foundation" not in evaluations
    assert "Agent builds</span><span class=\"tag\">foundation" not in agents
    assert evaluations.count('aria-current="page"') == 1
    assert agents.count('aria-current="page"') == 1


def test_evaluation_workbench_renders_registered_objects(client, monkeypatch):
    import app as webui_module

    payloads = {
        "/agent-builds": {"builds": [{"id": "build-1", "name": "Researcher",
            "version": "v1", "driver": "scripted-mcp/v1", "digest": "sha256:abc"}]},
        "/eval-challenges": {"challenges": [{"id": "challenge-1", "name": "Grant",
            "version": "v1", "label": "calibration"}]},
        "/eval-suites": {"suites": [{"id": "suite-1", "name": "Web suite",
            "version": "v1", "challenge_ids": ["challenge-1"], "seeds": [1, 2, 3]}]},
        "/evaluations": {"evaluations": [{"id": "evaluation-1", "state": "completed"}]},
    }
    monkeypatch.setattr(webui_module, "_api_get", lambda path, **_kwargs: (payloads[path], True))
    _login(client)
    html = client.get("/evaluations").data.decode()
    assert "Researcher" in html and "Grant" in html and "Web suite" in html
    assert "Evaluation evaluati" in html
    assert 'id="suite-challenges"' in html
    assert "Needs one saved suite and two registered builds." in html
    registry = client.get("/library/agents").data.decode()
    assert "sha256:abc" in registry and "scripted-mcp/v1" in registry


def test_evaluation_detail_explains_calibration_and_interval(client, monkeypatch):
    import app as webui_module

    verified = {"mean": -1.0, "pairs": 5, "bootstrap_95": [-1.0, -1.0],
                "interval_status": "degenerate"}
    comparison = {"matched_pairs": 5, "infrastructure_failed_pairs": 0,
                  "evidence_scope": "calibration_only", "leakage_labels": ["calibration"],
                  "differences": {"verified": verified},
                  "verified_difference_range": [-1.0, -1.0],
                  "by_challenge": {"challenge-1": {"name": "Grant", "leakage_label": "calibration",
                      "matched_pairs": 5, "infrastructure_failed_pairs": 0,
                      "differences": {"verified": verified}}},
                  "pairs": [{"challenge_id": "challenge-1", "seed": 1,
                      "leakage_label": "calibration", "matched": True,
                      "baseline_state": "completed", "candidate_state": "completed",
                      "baseline": {"verified": 1, "false_claims": 0, "requests": 2,
                                   "latency_seconds": 1.0},
                      "candidate": {"verified": 0, "false_claims": 1, "requests": 2,
                                    "latency_seconds": 1.0}}]}
    record = {"id": "evaluation-1", "state": "completed", "comparison": comparison,
              "trials": [{"seed": 1, "state": "completed", "arena_id": "arena-1",
                          "error": None}]}
    monkeypatch.setattr(webui_module, "_api_get", lambda _path, **_kwargs: (record, True))
    _login(client)
    html = client.get("/evaluations/evaluation-1").data.decode()
    assert "Evidence scope: calibration_only" in html
    assert "degenerate" in html and "Grant" in html
    assert 'href="/arena/arena-1"' in html
    assert html.count('aria-current="page"') == 1


def _cross_arena_client(client, monkeypatch, findings=(), verdicts=(), signals=(),
                        deployments=None):
    """Wire the console to a fake orchestrator holding events across two arenas."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/deployments" in url and "/events" not in url:
            return _FakeResp(deployments if deployments is not None else {
                "arena-1": {"status": "active", "user_id": "web-review",
                            "scenario": "sut:app", "outputs": {}},
                "arena-2": {"status": "destroyed", "user_id": "past-run",
                            "scenario": "container_web_pentest", "outputs": {}},
            })
        if "type=finding_verification" in url:
            return _FakeResp({"events": list(verdicts)})
        if "type=finding" in url:
            return _FakeResp({"events": list(findings)})
        if "type=monitor_signal" in url:
            return _FakeResp({"events": list(signals)})
        if "/events" in url:
            return _FakeResp({"events": []})
        return _FakeResp({})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)


_FINDING_EVENTS = [
    {"id": 9, "lab_id": "arena-1", "ts": "2026-08-18 10:00:00", "type": "finding",
     "payload": {"finding_id": "f1", "title": "Reflected XSS in search", "cwe": "CWE-79",
                 "node": "victim", "manual": False,
                 "evidence_artifacts": [{"digest": "a" * 64, "bytes": 512}]}},
    {"id": 8, "lab_id": "arena-2", "ts": "2026-08-18 09:00:00", "type": "finding",
     "payload": {"finding_id": "f2", "title": "Weak cookie flags", "cwe": "CWE-614",
                 "node": "victim", "manual": True, "evidence_artifacts": []}},
]
_VERDICT_EVENTS = [
    {"id": 10, "lab_id": "arena-2", "ts": "2026-08-18 09:30:00",
     "type": "finding_verification",
     "payload": {"finding_id": "f2", "verdict": "confirmed", "actor": "admin"}},
]


def test_findings_index_spans_engagements_and_links_back(client, monkeypatch):
    _cross_arena_client(client, monkeypatch, findings=_FINDING_EVENTS,
                        verdicts=_VERDICT_EVENTS)
    html = client.get("/activity/findings").data.decode()
    assert "Reflected XSS in search" in html and "Weak cookie flags" in html
    # every row returns to the engagement that produced it
    assert "/arena/arena-1#findings" in html and "/arena/arena-2#findings" in html
    assert "web-review" in html and "past-run" in html
    # the operator verdict wins over the absent automatic one
    assert 'data-src="manual_confirmed"' in html
    assert 'data-src="inconclusive"' in html
    assert "1 awaiting review" in html


def test_evidence_index_lists_artifacts_and_signals(client, monkeypatch):
    signals = [{"id": 11, "lab_id": "arena-1", "ts": "2026-08-18 10:05:00",
                "type": "monitor_signal",
                "payload": {"kind": "crash", "node": "victim", "severity": "high",
                            "summary": "exited with code 139"}}]
    _cross_arena_client(client, monkeypatch, findings=_FINDING_EVENTS,
                        verdicts=_VERDICT_EVENTS, signals=signals)
    html = client.get("/activity/evidence").data.decode()
    assert "a" * 16 in html                       # artifact digest tail
    assert "/api/arenas/arena-1/evidence-artifacts/" in html
    assert "Reflected XSS in search" in html      # provenance stays attached
    assert "crash" in html and "exited with code 139" in html
    assert "/arena/arena-1#evidence" in html


def test_indexes_do_not_offer_links_into_a_pruned_engagement(client, monkeypatch):
    """Finding events outlive a deleted arena record — say so instead of linking nowhere."""
    _cross_arena_client(
        client, monkeypatch, findings=_FINDING_EVENTS, verdicts=_VERDICT_EVENTS,
        deployments={},  # every referenced engagement record is gone
    )
    findings_html = client.get("/activity/findings").data.decode()
    assert "Reflected XSS in search" in findings_html      # the finding still stands
    assert "/arena/arena-1#findings" not in findings_html  # but leads nowhere

    evidence_html = client.get("/activity/evidence").data.decode()
    assert "evidence-artifacts/" not in evidence_html      # nothing to download
    assert "unavailable" in evidence_html


def test_home_is_composed_from_product_objects(client, monkeypatch):
    deployments = {
        "arena-1": {"status": "active", "user_id": "web-review", "scenario": "sut:app",
                    "outputs": {"egress": "open"}},
        "arena-3": {"status": "failed", "user_id": "broken-run", "scenario": "sut:app",
                    "outputs": {}},
        "arena-2": {"status": "destroyed", "user_id": "past-run",
                    "scenario": "container_web_pentest", "outputs": {}},
    }
    _cross_arena_client(client, monkeypatch, findings=_FINDING_EVENTS,
                        verdicts=_VERDICT_EVENTS, deployments=deployments)
    html = client.get("/").data.decode()
    assert "Live engagements" in html and "web-review" in html
    assert "Findings awaiting review" in html and "Reflected XSS in search" in html
    # both attention kinds are stated, not buried
    assert "Needs attention" in html
    assert "broken-run" in html and "egress open" in html
    assert "Providers &amp; capacity" in html
    assert "/activity/findings" in html   # the review queue is one click away


def test_shared_toolbar_pattern_is_used_by_filterable_indexes(client):
    _login(client)
    assert 'class="toolbar"' in client.get("/activity/audit").data.decode()
    assert 'class="toolbar toolbar--spacious"' in client.get(
        "/library/challenges"
    ).data.decode()


@pytest.mark.parametrize(
    ("legacy_path", "target_path", "heading"),
    [
        ("/arenas", "/engagements", "Engagements"),
        ("/scenarios", "/library/challenges", "Challenge library"),
        ("/agents", "/activity/agents", "Agent activity"),
        ("/audit", "/activity/audit", "Audit trail"),
        ("/settings", "/administration/settings", "Settings"),
    ],
)
def test_target_routes_preserve_legacy_workflows(client, legacy_path, target_path, heading):
    _login(client)
    legacy = client.get(legacy_path)
    target = client.get(target_path)
    assert legacy.status_code == target.status_code == 200
    assert heading in legacy.data.decode()
    assert heading in target.data.decode()


def test_engagement_entry_sections_follow_the_operator_sequence(client):
    _login(client)
    html = client.get("/engagements/new").data.decode()
    legends = [
        "1. What is the purpose?",
        "2. What does it start from?",
        "3. Who will drive it?",
        "4. Runtime policy",
    ]
    positions = [html.index(legend) for legend in legends]
    assert positions == sorted(positions), "numbered steps must render in order"


@pytest.mark.parametrize("path", ["/launch", "/wizard"])
def test_journey_steps_mark_their_navigation_owner(client, path):
    """Compatibility builders are later steps of New engagement, not orphan pages."""
    _login(client)
    html = client.get(path).data.decode()
    assert html.count('aria-current="page"') == 1
    marked = html[: html.index('aria-current="page"')].rsplit("<a class=", 1)[-1]
    assert "nav-item--child active" in marked
    assert "New engagement" in html[html.index('aria-current="page"') :][:400]


def test_favicon_is_served_without_a_session(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 302
    assert "anvil_logo.png" in resp.headers["Location"]


def test_login_rejects_wrong_password_even_with_token(client):
    token = _csrf_token(client)
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "nope", "csrf_token": token},
    )
    assert resp.status_code == 200  # re-renders the login page
    assert client.get("/").status_code == 302  # still not logged in


def test_create_rejects_missing_csrf_token(client):
    _login(client)
    resp = client.post(
        "/create", data={"scenario": "basic_pentest", "instance_id": "lab-x"}
    )
    assert resp.status_code == 400


def test_destroy_rejects_missing_csrf_token(client):
    _login(client)
    assert client.post("/api/destroy/some-id").status_code == 400


def test_logout_rejects_missing_csrf_token(client):
    _login(client)
    assert client.post("/logout").status_code == 400
    assert client.get("/").status_code == 200  # still logged in


def test_arenas_separate_destroyed_into_archive(client, monkeypatch):
    """Destroyed arenas must leave the active list and land in the archive."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if url.endswith("/deployments"):
            return _FakeResp({
                "id-1": {"user_id": "lab-alive", "scenario": "basic_pentest",
                         "status": "active", "outputs": {}},
                "id-2": {"user_id": "lab-gone", "scenario": "basic_pentest",
                         "status": "destroyed", "outputs": {}},
            })
        return _FakeResp({"scenarios": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arenas").data.decode()

    assert "lab-alive" in html
    assert "Archive" in html and "lab-gone" in html
    # The destroyed arena appears only inside the archive section, which renders
    # below the active list — so it must come after the "Archive" heading.
    assert html.index("lab-gone") > html.index("Archive")
    assert html.index("lab-alive") < html.index("Archive")


def test_external_redirect_target_is_ignored(client):
    token = _csrf_token(client)
    resp = client.post(
        "/login?next=https://evil.example",
        data={"username": "admin", "password": "nidavellir", "csrf_token": token},
    )
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_login_preserves_internal_console_query_without_open_redirect(client):
    unauthenticated = client.get("/console/research/new?source=bundle")
    assert unauthenticated.status_code == 302
    assert "source%3Dbundle" in unauthenticated.headers["Location"]
    token = _csrf_token(client)
    response = client.post(
        "/login?next=/console/research/new?source=bundle",
        data={"username": "admin", "password": "nidavellir", "csrf_token": token},
    )
    assert response.headers["Location"] == "/console/research/new?source=bundle"
    for target in ("//evil.example/path", "/\\evil.example/path"):
        token = _csrf_token(client)
        result = client.post("/login", query_string={"next": target},
                             data={"username": "admin", "password": "nidavellir",
                                   "csrf_token": token})
        assert result.headers["Location"] in ("/", "http://localhost/")


def test_archive_routes_reject_missing_csrf_token(client):
    _login(client)
    assert client.post("/archive/delete/some-id").status_code == 400
    assert client.post("/archive/clear").status_code == 400
    assert client.post("/destroy/some-id").status_code == 400


def test_health_proxy_reports_offline_backend(client):
    # No login needed: the badge polls this from the login page too.
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "offline"}  # ORCHESTRATOR_URL is a closed port


def test_health_proxy_reports_online_backend(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

    monkeypatch.setattr(webui_module.requests, "get", lambda *a, **kw: _FakeResp())
    resp = client.get("/api/health")
    assert resp.get_json() == {"status": "ok"}


def test_api_destroy_relays_backend_failure(client):
    """The JSON destroy proxy must not claim success when the backend is down."""
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/api/destroy/some-id", headers={"X-CSRFToken": token})
    assert resp.status_code == 502
    assert "error" in resp.get_json()


def test_destroy_form_route_redirects_with_flash(client):
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/destroy/some-id", data={"csrf_token": token})
    assert resp.status_code == 302  # back to the lobby with a flash, not a 500


def test_arenas_archive_offers_cleanup_controls(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if url.endswith("/deployments"):
            return _FakeResp({
                "id-2": {"user_id": "lab-gone", "scenario": "basic_pentest",
                         "status": "destroyed", "outputs": {}},
            })
        return _FakeResp({"scenarios": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arenas").data.decode()

    assert "/archive/clear" in html
    assert "/archive/delete/id-2" in html


def test_arena_detail_renders_challenges_panel(client, monkeypatch):
    """The arena detail page shows the known-vuln manifest with found/missed."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp({"user_id": "lab-x", "status": "active", "outputs": {}})
        if url.rstrip("/").endswith("/score") or "/score?" in url:
            return _FakeResp({
                "arena_id": "abc", "scenario": "s", "mode": "benchmark",
                "score": {"value": 0.5, "value_kind": "numeric",
                          "answer": "1/2 known vulnerabilities discovered",
                          "explanation": "", "evidence": {}, "metadata": {}},
                "progress_rate": 0.6, "tier": "partial",
                "milestones": [
                    {"id": "foothold", "reached": True, "detail": "x"},
                    {"id": "recon", "reached": True, "detail": "x"},
                    {"id": "first_blood", "reached": True, "detail": "x"},
                    {"id": "verified_exploit", "reached": False, "detail": "x"},
                    {"id": "full_clear", "reached": False, "detail": "x"},
                ],
                "total_vulnerabilities": 2, "found": ["sqli-login"], "missed": ["xss"],
                "confirmed": [], "confirmed_findings": 0,
                "points_earned": 1, "points_total": 2, "findings_submitted": 1,
                "signals": {"counts": {}, "distinct_fault_sites": 0, "fault_nodes": []},
                "metrics": {"steps": 3},
                "manifest": [
                    {"id": "sqli-login", "title": "SQL injection", "cwe": "CWE-89",
                     "node": "victim", "severity": "high"},
                    {"id": "xss", "title": "Reflected XSS", "cwe": "CWE-79",
                     "node": "victim", "severity": "medium"},
                ],
            })
        return _FakeResp({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/abc").data.decode()

    assert "Assessment" in html          # the mode-aware result panel
    assert "known-vuln lab" in html       # benchmark framing
    assert "Challenges" in html
    assert "SQL injection" in html and "CWE-89" in html
    assert "1 / 2 found" in html
    assert "found" in html and "open" in html  # the discovered one + the missed one


def test_mock_engagement_is_labelled_and_has_no_live_target_link(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **_kwargs):
        if "/status/" in url:
            return _FakeResp({"user_id": "demo-web", "status": "active",
                "scenario": "container_web_pentest", "provider": "mock",
                "outputs": {"node_victim_name": "victim",
                            "node_victim_url": "http://192.168.50.10",
                            "node_victim_state": "running"}})
        if "/score" in url:
            return _FakeResp({})
        return _FakeResp({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/demo-web").data.decode()
    assert 'id="mock-provider-notice"' in html
    assert "UI demonstration only" in html
    assert 'href="http://192.168.50.10"' not in html


def test_arena_detail_renders_discovery_score_and_findings(client, monkeypatch):
    """A SUT / discovery arena (no manifest) still shows the Assessment panel and
    a Findings list — the gap this fixes."""
    import app as webui_module

    class _R:
        status_code = 200

        def __init__(self, p):
            self._p = p

        def json(self):
            return self._p

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _R({"user_id": "sut-x", "status": "active", "scenario": "custom:x",
                       "outputs": {}})
        if "/score" in url:
            return _R({"mode": "discovery", "score": {"value": 1.0, "answer": "1 fault site"},
                       "progress_rate": 1.0, "tier": "complete", "total_vulnerabilities": 0,
                       "found": [], "missed": [], "confirmed": [], "confirmed_findings": 1,
                       "points_earned": 0, "points_total": 0, "findings_submitted": 1,
                       "signals": {"counts": {"crash": 1}, "distinct_fault_sites": 1,
                                   "fault_nodes": ["victim"]},
                       "milestones": [{"id": "foothold", "reached": True, "detail": "x"}],
                       "manifest": []})
        if "/events" in url:
            return _R({"events": [{"id": 1, "type": "finding", "ts": "t",
                                   "payload": {"title": "crash via input", "cwe": "CWE-89",
                                               "node": "victim", "matched_vuln_id": None,
                                               "validation": {"confirmed": True, "method": "crash_signal"}}}]})
        return _R({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/sut-x").data.decode()
    assert "Assessment" in html and "discovery" in html
    assert "Findings" in html and "crash via input" in html
    assert "confirmed" in html
    assert 'id="challenges-panel"' not in html  # no manifest -> no spoiler panel for a SUT


def test_arena_detail_surfaces_durable_engagement_intent(client, monkeypatch):
    import app as webui_module

    monkeypatch.setattr(
        webui_module,
        "_api_get",
        lambda path: ({"user_id": "intent-lab", "status": "active", "outputs": {}}, True),
    )
    monkeypatch.setattr(
        webui_module,
        "_events",
        lambda *args, **kwargs: [
            {
                "type": "engagement_intent",
                "payload": {"purpose": "benchmark", "source": "challenge"},
            }
        ],
    )
    monkeypatch.setattr(webui_module, "_score", lambda instance_id: None)
    monkeypatch.setattr(webui_module, "_findings", lambda instance_id: [])
    monkeypatch.setattr(webui_module, "_setup_steps", lambda instance_id: [])

    _login(client)
    html = client.get("/arena/intent-lab").data.decode()
    assert "Immutable engagement intent" in html
    assert "benchmark" in html


def test_current_agent_disconnected_when_no_session(client):
    """With the backend at a closed port, no events → no connected model."""
    _login(client)
    resp = client.get("/api/current-agent")
    assert resp.status_code == 200
    assert resp.get_json() == {"connected": False}


def test_current_agent_reports_latest_announced_model(client, monkeypatch):
    """The chip endpoint surfaces the newest agent_session event's model/provider."""
    import app as webui_module

    monkeypatch.setattr(webui_module, "_events", lambda limit=100, type=None: [
        {"type": "agent_exec", "lab_id": "arena-9", "payload": {"node": "kali"}},
        {"type": "agent_session", "lab_id": "arena-9", "ts": "2026-06-18 10:00:00",
         "actor": "agent-x",
         "payload": {"model": "gemini-2.0-flash", "provider": "Gemini", "stance": "attacker"}},
    ])
    _login(client)
    data = client.get("/api/current-agent").get_json()
    assert data["connected"] is True
    assert data["model"] == "gemini-2.0-flash"
    assert data["provider"] == "gemini"   # lower-cased for the logo lookup
    assert data["arena_id"] == "arena-9"
    assert data["stance"] == "attacker"


# --- model-connection bubble (BYO key) proxy --------------------------------

def test_model_connection_get_offline_reports_unconfigured(client):
    """With the backend down, the bubble endpoint degrades to 'not configured'."""
    _login(client)
    resp = client.get("/api/model-connection")
    assert resp.status_code == 200
    assert resp.get_json() == {"configured": False}


def test_model_connection_put_requires_csrf(client):
    """Storing a key is a state change → CSRF-protected (no token = rejected)."""
    _login(client)
    resp = client.put(
        "/api/model-connection",
        json={"provider": "anthropic", "model": "claude-opus-4-8", "api_key": "k"},
    )
    assert resp.status_code == 400  # CSRF missing


def test_model_connection_delete_requires_csrf(client):
    _login(client)
    assert client.delete("/api/model-connection").status_code == 400


def test_model_connection_put_relays_unreachable_backend(client):
    """With CSRF satisfied but the orchestrator at a closed port, the proxy
    reports the backend as unreachable rather than 500-ing."""
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.put(
        "/api/model-connection",
        json={"provider": "anthropic", "model": "claude-opus-4-8", "api_key": "k"},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 502
    assert "unreachable" in resp.get_json()["error"]


def test_model_connection_verify_requires_csrf(client):
    _login(client)
    assert client.post("/api/model-connection/verify", json={}).status_code == 400


def test_model_connection_verify_offline_is_unchecked(client):
    """The test-connection proxy degrades to checked=False when the backend is
    unreachable (never a false 'invalid key')."""
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post(
        "/api/model-connection/verify",
        json={"provider": "openai", "model": "gpt-4o", "api_key": "k"},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["verified"] is False and body["checked"] is False


def test_copilot_requires_csrf(client):
    _login(client)
    assert client.post("/api/copilot", json={"messages": []}).status_code == 400


def test_copilot_offline_streams_error(client):
    """With the orchestrator at a closed port, the co-pilot proxy streams a clear
    error rather than 500-ing (the stream still has status 200)."""
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post(
        "/api/copilot",
        json={"messages": [{"role": "user", "content": "hi"}], "arena_id": None},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200
    assert b"unreachable" in resp.data


def test_setup_status_proxy_offline(client):
    _login(client)
    resp = client.get("/api/setup/some-arena")
    assert resp.status_code == 200 and resp.get_json() == {"open": False}


def test_setup_start_requires_csrf(client):
    _login(client)
    assert client.post("/api/setup/a/start", json={"mode": "operator"}).status_code == 400


def test_setup_start_relays_unreachable_backend(client):
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/api/setup/a/start", json={"mode": "operator"},
                       headers={"X-CSRFToken": token})
    assert resp.status_code == 502 and "unreachable" in resp.get_json()["error"]


def test_setup_decision_proxy_validates_decision(client):
    _login(client)
    token = _csrf_token(client, "/")
    bad = client.post("/api/setup/a/proposals/x/sideways", headers={"X-CSRFToken": token})
    assert bad.status_code == 400


# --- scenario authoring & import proxies (P1-7) + topology preview (P7-9) ----


def test_scenario_preview_proxy_requires_csrf(client):
    _login(client)
    assert client.post("/api/scenarios/preview", json={"spec": "x"}).status_code == 400


def test_scenario_import_proxy_requires_csrf(client):
    _login(client)
    assert client.post("/api/scenarios/import", json={"spec": "x"}).status_code == 400


def test_scenario_delete_proxy_requires_csrf(client):
    _login(client)
    assert client.delete("/api/scenarios/some-id").status_code == 400


def test_scenario_preview_proxy_relays_unreachable_backend(client):
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/api/scenarios/preview", json={"spec": "x"},
                       headers={"X-CSRFToken": token})
    assert resp.status_code == 502 and "error" in resp.get_json()


def test_scenario_topology_proxy_offline_is_404(client):
    _login(client)
    resp = client.get("/api/scenarios/whatever/topology")
    # backend is a closed port → _api_get fails → proxy returns 404 + null topology
    assert resp.status_code == 404
    assert resp.get_json()["topology"] is None


def test_workspace_list_proxy_and_diff_proxy(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/workspaces"):
            return _FakeResp({"workspaces": [{"node": "victim", "writable": True}]})
        return _FakeResp({
            "success": True, "changed_file_count": 1, "changed_files": [],
            "diff": "+safe", "returned_lines": 1, "total_lines": 1,
        })

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    listed = client.get("/api/arenas/a1/workspaces")
    assert listed.status_code == 200
    assert listed.get_json()["workspaces"][0]["node"] == "victim"

    diff = client.get(
        "/api/arenas/a1/workspaces/victim/diff?base=HEAD&path=src/app.py&max_lines=50"
    )
    assert diff.status_code == 200 and diff.get_json()["diff"] == "+safe"
    assert calls[-1][1]["params"]["path"] == "src/app.py"


def test_arena_detail_contains_shared_workspace_viewer(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp({
                "user_id": "research", "status": "active", "scenario": "sut:local",
                "outputs": {"node_victim_name": "nv-victim"},
            })
        if url.endswith("/workspaces"):
            return _FakeResp({"workspaces": [{"node": "victim", "path": "/srv/app"}]})
        if "/score" in url:
            return _FakeResp({})
        return _FakeResp({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/a1").data
    assert b'id="workspace-card"' in html
    assert b"Workspace changes" in html
    # The viewer lives in the Changes tab of the workspace (ROADMAP C3).
    assert b'data-tab="changes"' in html


def test_workspace_hides_tabs_that_have_nothing_to_show(client, monkeypatch):
    """Only applicable tabs render — an arena with no workspaces has no Changes tab."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp({
                "user_id": "lab", "status": "active", "scenario": "container_web_pentest",
                "outputs": {"node_victim_name": "nv-victim"},
            })
        if url.endswith("/workspaces"):
            return _FakeResp({"workspaces": []})
        if "/score" in url:
            return _FakeResp({})
        return _FakeResp({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/a1").data.decode()
    for always in ("overview", "live", "findings", "agent", "infrastructure"):
        assert f'data-tab="{always}"' in html
    for absent in ("changes", "evidence", "trace"):
        assert f'data-tab="{absent}"' not in html


def test_destroyed_engagement_is_a_read_only_record(client, monkeypatch):
    """Evidence outlives the arena; nothing may be run against infrastructure that is gone."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp({
                "user_id": "past-run", "status": "destroyed",
                "scenario": "sut:local", "outputs": {},
            })
        if url.endswith("/workspaces"):
            return _FakeResp({"workspaces": []})
        if "/score" in url:
            return _FakeResp({})
        return _FakeResp({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/a1").data.decode()
    assert 'id="readonly-notice"' in html
    assert "read-only record" in html
    assert "destroyInstance(" not in html          # no lifecycle action
    assert "Nidavellir.openConfigurator()" not in html  # nothing to configure
    assert 'id="findings-card"' in html            # evidence stays reviewable
    assert 'badge--ok">running' not in html        # never claim a destroyed node is up


def _stream_frames(client, monkeypatch, events, headers=None):
    """Read one pass of the workspace stream without waiting on its idle sleep."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp({"status": "active", "outputs": {"node_victim_name": "v"}})
        return _FakeResp({"events": events})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    # One iteration is enough: the loop exits as soon as its deadline passes.
    monkeypatch.setattr(webui_module, "_STREAM_MAX_SECONDS", 0.001)
    monkeypatch.setattr(webui_module.time, "sleep", lambda _s: None)
    _login(client)
    resp = client.get("/api/arenas/a1/stream", headers=headers or {})
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    return resp.get_data(as_text=True)


def test_workspace_stream_pushes_state_and_activity(client, monkeypatch):
    body = _stream_frames(client, monkeypatch, [
        {"id": 7, "type": "finding", "ts": "t", "payload": {"title": "XSS"}},
        {"id": 6, "type": "status", "ts": "t", "payload": {"to": "active"}},
    ])
    assert "event: state" in body
    assert '"status": "active"' in body
    assert "event: activity" in body
    assert "id: 7" in body            # cursor is the newest event id
    assert "XSS" in body


def test_workspace_stream_resumes_from_last_event_id(client, monkeypatch):
    """A reconnecting browser must not replay what it already rendered."""
    body = _stream_frames(
        client, monkeypatch,
        [{"id": 7, "type": "finding", "ts": "t", "payload": {"title": "XSS"}},
         {"id": 6, "type": "status", "ts": "t", "payload": {"to": "active"}}],
        headers={"Last-Event-ID": "7"},
    )
    assert "event: activity" not in body   # nothing newer than the cursor
    assert "keepalive" in body


def test_eval_export_proxy_downloads_the_run_row(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"source_trace_id": "trace-1", "metadata": {"run_id": "a1"}}

    monkeypatch.setattr(webui_module.requests, "get", lambda url, **kw: _FakeResp())
    _login(client)
    resp = client.get("/api/arenas/a1/eval-export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["Content-Disposition"]
    assert b"trace-1" in resp.data


def test_manual_finding_form_starts_hidden(client, monkeypatch):
    """An inline display: would defeat the hidden attribute — the form styles by class."""
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp({"user_id": "lab", "status": "active",
                              "scenario": "container_web_pentest", "outputs": {}})
        if url.endswith("/workspaces"):
            return _FakeResp({"workspaces": []})
        if "/score" in url:
            return _FakeResp({})
        return _FakeResp({"events": []})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)
    html = client.get("/arena/a1").data.decode()
    form = html[html.index('id="mf-form"'):html.index('id="mf-form"') + 120]
    assert "hidden" in form
    assert "display:grid" not in form


def test_vulhub_import_proxy_requires_csrf(client):
    _login(client)
    assert client.post(
        "/api/scenarios/import/vulhub", json={"path": "a/b"}
    ).status_code == 400


def test_vulhub_import_proxy_relays_unreachable_backend(client):
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/api/scenarios/import/vulhub", json={"path": "a/b"},
                       headers={"X-CSRFToken": token})
    assert resp.status_code == 502 and "error" in resp.get_json()


def test_wizard_page_renders(client):
    _login(client)
    r = client.get("/wizard")
    assert r.status_code == 200
    assert b"New engagement from target" in r.data and b"wiz-form" in r.data
    assert b"authorization_confirmed" in r.data
    assert b"authorized to assess it" in r.data
    assert b'option value="oci"' in r.data
    assert b'option value="bundle"' in r.data
    assert b'name="image"' in r.data
    assert b'multipart/form-data' in r.data


def test_preflight_proxy_returns_target_readiness(client, monkeypatch):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "status": "passed",
                "ready": True,
                "target": {"identity": {"digest": "a" * 40}},
            }

    monkeypatch.setattr(webui_module.requests, "get", lambda *a, **k: _FakeResp())
    _login(client)
    response = client.get("/api/arenas/a1/preflight")
    assert response.status_code == 200
    assert response.get_json()["ready"] is True


def test_workspace_patch_proxy_relays_evidence_options(client, monkeypatch):
    import app as webui_module

    captured = {}

    def fake_post(path, payload):
        captured.update(path=path, payload=payload)
        return {"artifact": {"digest": "sha256:" + "a" * 64}}, 200

    monkeypatch.setattr(webui_module, "_api_post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    response = client.post(
        "/api/arenas/a1/workspaces/victim/patch-artifacts",
        json={
            "base": "HEAD",
            "path": "notes.txt",
            "include_untracked_paths": ["notes.txt"],
        },
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert captured["path"].endswith("/workspaces/victim/patch-artifacts")
    assert captured["payload"]["include_untracked_paths"] == ["notes.txt"]


def test_manual_finding_proxy_relays_evidence_digest(client, monkeypatch):
    import app as webui_module

    captured = {}
    monkeypatch.setattr(
        webui_module,
        "_api_post",
        lambda path, payload: (captured.update(path=path, payload=payload) or {}, 200),
    )
    _login(client)
    token = _csrf_token(client, "/")
    digest = "sha256:" + "b" * 64
    response = client.post(
        "/api/arenas/a1/findings/manual",
        json={"title": "finding", "evidence_artifact_digests": [digest]},
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert captured["payload"]["evidence_artifact_digests"] == [digest]


def test_sut_preview_proxy_relays_unreachable_backend(client):
    _login(client)
    token = _csrf_token(client, "/")
    r = client.post("/api/arenas/sut/preview",
                    json={"instance_id": "w", "repo": "https://github.com/o/p"},
                    headers={"X-CSRFToken": token})
    assert r.status_code == 502 and "error" in r.get_json()


def test_oci_preview_proxy_selects_oci_endpoint(client, monkeypatch):
    import app as webui_module

    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"valid": True}, 200

    monkeypatch.setattr(webui_module, "_api_post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    response = client.post(
        "/api/arenas/sut/preview",
        json={
            "target_type": "oci",
            "instance_id": "oci-preview",
            "image": "nginx:1.27",
            "platform": "linux/arm64",
            "authorization_confirmed": True,
        },
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert captured["path"] == "/arenas/oci/preview"
    assert captured["payload"]["image"] == "nginx:1.27"
    assert captured["payload"]["platform"] == "linux/arm64"
    assert "repo" not in captured["payload"]


def test_bundle_preview_proxy_selects_bundle_endpoint(client, monkeypatch):
    import app as webui_module

    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"valid": True}, 200

    monkeypatch.setattr(webui_module, "_api_post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    response = client.post(
        "/api/arenas/sut/preview",
        json={
            "target_type": "bundle",
            "instance_id": "bundle-preview",
            "artifact_digest": "sha256:" + "a" * 64,
            "authorization_confirmed": True,
        },
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert captured["path"] == "/arenas/source-bundle/preview"
    assert captured["payload"]["artifact_digest"] == "sha256:" + "a" * 64


def test_source_bundle_upload_proxy_streams_multipart(client, monkeypatch):
    import io

    import app as webui_module

    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"artifact": {"digest": "sha256:" + "b" * 64}}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["files"] = kwargs["files"]
        return _FakeResp()

    monkeypatch.setattr(webui_module.requests, "post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    response = client.post(
        "/api/targets/source-bundles",
        data={"file": (io.BytesIO(b"tar bytes"), "project.tar")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert captured["url"].endswith("/targets/source-bundles")
    assert captured["files"]["file"][0] == "project.tar"


def test_grant_binding_proxy_requires_csrf(client):
    _login(client)
    assert client.post("/api/arenas/a1/bindings",
                       json={"agent_name": "x", "stance": "attacker"}).status_code == 400


def test_grant_binding_proxy_relays_name_and_stance(client, monkeypatch):
    import app as webui_module

    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"bound": True}

    def fake_post(url, json=None, **kwargs):
        captured["url"], captured["json"] = url, json
        return _FakeResp()

    monkeypatch.setattr(webui_module.requests, "post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    r = client.post("/api/arenas/a1/bindings",
                    json={"agent_name": "  red-team  ", "stance": "attacker"},
                    headers={"X-CSRFToken": token})
    assert r.status_code == 200
    assert captured["url"].endswith("/arenas/a1/bindings")
    assert captured["json"] == {"agent_name": "red-team", "stance": "attacker"}


def test_list_bindings_proxy_offline_returns_empty(client):
    _login(client)
    data = client.get("/api/arenas/a1/bindings").get_json()
    assert data == {"bindings": []}   # backend offline → empty, not a 500


def test_pause_resume_proxy_requires_csrf(client):
    _login(client)
    assert client.post("/api/arenas/a1/bindings/x/pause").status_code == 400
    assert client.post("/api/arenas/a1/bindings/x/resume").status_code == 400


def test_pause_resume_proxy_relays_to_orchestrator(client, monkeypatch):
    import app as webui_module

    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"paused": True, "agent_name": "red-team"}

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        return _FakeResp()

    monkeypatch.setattr(webui_module.requests, "post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    r = client.post("/api/arenas/a1/bindings/red-team/pause", headers={"X-CSRFToken": token})
    assert r.status_code == 200 and r.get_json()["paused"] is True
    assert captured["url"].endswith("/arenas/a1/bindings/red-team/pause")
    client.post("/api/arenas/a1/bindings/red-team/resume", headers={"X-CSRFToken": token})
    assert captured["url"].endswith("/arenas/a1/bindings/red-team/resume")


def test_scenario_generate_proxy_requires_csrf(client):
    _login(client)
    assert client.post(
        "/api/scenarios/generate", json={"prompt": "a dvwa lab"}
    ).status_code == 400


def test_scenario_generate_proxy_relays_unreachable_backend(client):
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/api/scenarios/generate", json={"prompt": "x"},
                       headers={"X-CSRFToken": token})
    assert resp.status_code == 502 and "error" in resp.get_json()


def test_scenario_generate_proxy_relays_prompt_and_class(client, monkeypatch):
    """The generate proxy forwards the prompt + provider_class to the orchestrator."""
    import app as webui_module

    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"valid": True, "spec": {}, "topology": {}}

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp()

    monkeypatch.setattr(webui_module.requests, "post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post(
        "/api/scenarios/generate",
        json={"prompt": "  a redis box  ", "provider_class": "container"},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200
    assert captured["url"].endswith("/scenarios/generate")
    assert captured["json"] == {"prompt": "a redis box", "provider_class": "container"}


def test_build_custom_posts_multiple_attackers(client, monkeypatch):
    """The custom-build form relays an `attackers` list to the orchestrator."""
    import app as webui_module

    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {}

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp()

    from werkzeug.datastructures import MultiDict

    monkeypatch.setattr(webui_module.requests, "post", fake_post)
    _login(client)
    token = _csrf_token(client, "/")
    resp = client.post("/build-custom", data=MultiDict([
        ("instance_id", "multi"),
        ("engagement_purpose", "calibration"),
        ("participant_mode", "mixed"),
        ("engagement_time_box_seconds", "7200"),
        ("attackers", "kali-cli"),
        ("attackers", "ubuntu"),
        ("victims", "dvwa"),
        ("csrf_token", token),
    ]))
    assert resp.status_code == 302
    assert captured["url"].endswith("/arenas/custom")
    assert captured["json"]["attackers"] == ["kali-cli", "ubuntu"]
    assert captured["json"]["engagement_purpose"] == "calibration"
    assert captured["json"]["participant_mode"] == "mixed"
    assert captured["json"]["engagement_time_box_seconds"] == 7200


def _arena_page_client(client, monkeypatch, *, outputs, tx_total=0):
    """Fake orchestrator for one arena page render (HTTP tab checks)."""
    import app as webui_module

    class _FakeResp:
        def __init__(self, payload, status=200):
            self._payload, self.status_code = payload, status

        def json(self):
            return self._payload

    state = {"status": "active", "user_id": "web-review",
             "scenario": "container_web_pentest", "outputs": outputs,
             "created_at": "2026-08-24 10:00:00", "expires_at": None}

    def fake_get(url, **kwargs):
        if "/status/arena-1" in url:
            return _FakeResp(state)
        if "/http/transactions" in url:
            return _FakeResp({"total": tx_total, "transactions": []})
        return _FakeResp({})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    _login(client)


_WEB_OUTPUTS = {
    "node_victim_name": "nv-victim",
    "node_victim_private_ip": "172.30.0.2",
    "node_victim_ports": {"80": "32768"},
    "node_attacker_name": "nv-attacker",
    "node_attacker_private_ip": "172.30.0.3",
    "node_attacker_ssh_command": "docker exec nv-attacker sh",
}


def test_arena_http_tab_renders_where_a_web_target_exists(client, monkeypatch):
    _arena_page_client(client, monkeypatch, outputs=_WEB_OUTPUTS, tx_total=3)
    html = client.get("/arena/arena-1").data.decode()
    assert 'data-tab="http"' in html
    assert 'id="wspanel-http"' in html
    assert ">3</span>" in html          # tab count badge


def test_arena_http_tab_hidden_without_web_target_or_transactions(
    client, monkeypatch,
):
    _arena_page_client(
        client, monkeypatch,
        outputs={"node_attacker_name": "nv-a",
                 "node_attacker_ssh_command": "docker exec nv-a sh"},
        tx_total=0,
    )
    html = client.get("/arena/arena-1").data.decode()
    assert 'id="wstab-http"' not in html


def test_http_transaction_proxies_forward_to_the_orchestrator(
    client, monkeypatch,
):
    import app as webui_module

    class _FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    seen_get, seen_post = [], []

    def fake_get(url, **kwargs):
        seen_get.append(url)
        if "/http/transactions" in url:
            if "/sha256%3A" in url and not url.endswith("/replay"):
                return _FakeResp({"manifest": {"digest": "x"}, "transaction": {}})
            return _FakeResp({"total": 0, "transactions": []})
        return _FakeResp({})

    def fake_post(url, **kwargs):
        seen_post.append((url, kwargs.get("json")))
        return _FakeResp({"success": True})

    monkeypatch.setattr(webui_module.requests, "get", fake_get)
    monkeypatch.setattr(webui_module.requests, "post", fake_post)
    _login(client)

    listed = client.get("/api/arenas/arena-1/http/transactions?limit=5&offset=2")
    assert listed.status_code == 200
    assert any(url.endswith("/arenas/arena-1/http/transactions?limit=5&offset=2")
               for url in seen_get)

    fetched = client.get(
        "/api/arenas/arena-1/http/transactions/sha256%3A" + "a" * 64
    )
    assert fetched.status_code == 200
    assert fetched.get_json()["manifest"]["digest"] == "x"

    token = _csrf_token(client, "/")
    driven = client.post(
        "/api/arenas/arena-1/http/request",
        json={"node": "victim", "path": "/", "method": "GET"},
        headers={"X-CSRFToken": token},
    )
    assert driven.status_code == 200
    assert seen_post[-1][0].endswith("/arenas/arena-1/http/request")
    assert seen_post[-1][1]["node"] == "victim"

    replayed = client.post(
        "/api/arenas/arena-1/http/transactions/"
        + "sha256%3A" + "a" * 64 + "/replay",
        json={"params": {"q": "1"}},
        headers={"X-CSRFToken": token},
    )
    assert replayed.status_code == 200
    assert seen_post[-1][0].endswith("/replay")
    assert seen_post[-1][1] == {"params": {"q": "1"}}


def test_console_arena_score_projects_scorecard_and_handles_absence(client, monkeypatch):
    import app as webui_module

    assert _login(client).status_code == 302
    monkeypatch.setattr(webui_module, "_api_get", lambda path, timeout=5: (None, False))
    assert client.get("/api/console/arenas/arena-1/score").get_json() == {"score": None}
    monkeypatch.setattr(webui_module, "_api_get", lambda path, timeout=5: ({
        "mode": "benchmark", "score": {"value": 0.5, "explanation": "private"},
        "tier": "partial", "progress_rate": 0.5,
        "milestones": [{"id": "foothold", "reached": True, "detail": "shell", "secret": 1}],
        "signals": {"distinct_fault_sites": 1, "counts": {"crash": 2}, "raw": ["x"]},
        "confirmed_findings": 1, "findings_submitted": 2,
        "total_vulnerabilities": 2, "found": ["v1"], "points_earned": 10, "points_total": 30,
        "manifest": [{"id": "v1", "title": "IDOR", "cwe": "CWE-639", "node": "api",
                      "severity": "high", "flag": "do-not-leak"}],
    }, True))
    score = client.get("/api/console/arenas/arena-1/score").get_json()["score"]
    assert score["mode"] == "benchmark" and score["value"] == 0.5
    assert score["milestones"] == [{"id": "foothold", "reached": True, "detail": "shell"}]
    assert score["signals"] == {"distinct_fault_sites": 1, "counts": {"crash": 2}}
    assert score["manifest"] == [{"id": "v1", "title": "IDOR", "cwe": "CWE-639",
                                  "node": "api", "severity": "high", "found": True}]
    assert "do-not-leak" not in str(score) and "private" not in str(score)


def test_console_arena_trace_reports_self_declared_attribution(client, monkeypatch):
    import app as webui_module

    assert _login(client).status_code == 302
    monkeypatch.setattr(webui_module, "_events", lambda *args, **kwargs: [])
    assert client.get("/api/console/arenas/arena-1/trace").get_json() == {"trace": None}
    monkeypatch.setattr(webui_module, "_events", lambda *args, **kwargs: [
        {"type": "agent_session", "payload": {}}])
    monkeypatch.setattr(webui_module, "_api_get", lambda path, timeout=5: ({
        "source_trace_id": "t-1", "input": "hidden",
        "metadata": {"gen_ai.request.model": "m", "gen_ai.system": "p",
                     "scaffold": "s", "stance": "attacker", "api_key": "no"}}, True))
    trace = client.get("/api/console/arenas/arena-1/trace").get_json()["trace"]
    assert trace == {"model": "m", "provider": "p", "scaffold": "s", "stance": "attacker",
                     "trace_id": "t-1", "export": "/api/arenas/arena-1/eval-export"}


def test_console_arena_forwards_list_open_and_revoke(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    headers = {"X-CSRFToken": token}

    def api_get(path, timeout=5):
        if path.endswith("/capabilities"):
            return {"operations": {"forward": {"state": "ready", "reason": ""}},
                    "footholds": ["kali"],
                    "targets": [{"node": "api", "forward_services": ["http"]}]}, True
        if path.endswith("/forwards"):
            return {"forwards": [{"id": "f1", "target": "api", "service_id": "http",
                                  "state": "open", "expires_at": "soon", "token": "x"}]}, True
        return None, False

    monkeypatch.setattr(webui_module, "_api_get", api_get)
    listed = client.get("/api/console/arenas/arena-1/forwards").get_json()
    assert listed["state"] == "ready" and listed["footholds"] == ["kali"]
    assert listed["services"] == [{"target": "api", "service": "http"}]
    assert listed["forwards"] == [{"id": "f1", "target": "api", "service_id": "http",
                                   "state": "open", "expires_at": "soon"}]
    path = "/api/console/arenas/arena-1/forwards"
    body = {"foothold": "kali", "target": "api", "service_id": "http"}
    assert client.post(path, json=body).status_code == 400
    assert client.post(path, json={**body, "target": "../x"}, headers=headers).status_code == 422
    calls = []
    monkeypatch.setattr(webui_module, "_api_post", lambda target, payload=None: (
        calls.append((target, payload)) or {"id": "f2"}, 200))
    assert client.post(path, json=body, headers=headers).status_code == 200
    target, payload = calls[0]
    assert target == "/arenas/arena-1/forwards"
    assert payload["lifetime_seconds"] == 120 and payload["target"] == "api"
    assert len(payload["idempotency_key"]) == 32
    assert client.post(path + "/f1/revoke", headers=headers).status_code == 200
    assert calls[1] == ("/arenas/arena-1/forwards/f1/revoke", None)


def test_console_archive_delete_and_clear_require_csrf_and_report_service_result(client, monkeypatch):
    import app as webui_module

    token = _csrf_token(client)
    assert _login(client).status_code == 302
    headers = {"X-CSRFToken": token}
    assert client.post("/api/console/archive/arena-1/delete").status_code == 400
    calls = []

    class Response:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    def delete(url, headers=None, timeout=None):
        calls.append(url)
        if url.endswith("/deployments"):
            return Response(200, {"deleted": 3})
        return Response(409, {"detail": "Arena is still active"})

    monkeypatch.setattr(webui_module.requests, "delete", delete)
    refused = client.post("/api/console/archive/arena-1/delete", headers=headers)
    assert refused.status_code == 409
    assert refused.get_json() == {"error": "Arena is still active"}
    cleared = client.post("/api/console/archive/clear", headers=headers)
    assert cleared.status_code == 200 and cleared.get_json() == {"deleted": 3}
    assert calls[0].endswith("/deployments/arena-1") and calls[1].endswith("/deployments")
