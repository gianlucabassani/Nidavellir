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


def test_routes_require_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_rejects_missing_csrf_token(client):
    resp = client.post("/login", data={"username": "admin", "password": "nidavellir"})
    assert resp.status_code == 400


def test_login_with_token_and_valid_credentials(client):
    resp = _login(client)
    assert resp.status_code == 302
    assert client.get("/").status_code == 200  # session established


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
                "total_vulnerabilities": 2, "found": ["sqli-login"], "missed": ["xss"],
                "points_earned": 1, "points_total": 2, "findings_submitted": 1,
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

    assert "Challenges" in html
    assert "SQL injection" in html and "CWE-89" in html
    assert "1 / 2 found" in html
    assert "found" in html and "open" in html  # the discovered one + the missed one


def test_current_agent_disconnected_when_no_session(client):
    """With the backend at a closed port, no events → no connected model."""
    _login(client)
    resp = client.get("/api/current-agent")
    assert resp.status_code == 200
    assert resp.get_json() == {"connected": False}


def test_current_agent_reports_latest_announced_model(client, monkeypatch):
    """The chip endpoint surfaces the newest agent_session event's model/provider."""
    import app as webui_module

    monkeypatch.setattr(webui_module, "_events", lambda limit=100: [
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
        ("attackers", "kali-cli"),
        ("attackers", "ubuntu"),
        ("victims", "dvwa"),
        ("csrf_token", token),
    ]))
    assert resp.status_code == 302
    assert captured["url"].endswith("/arenas/custom")
    assert captured["json"]["attackers"] == ["kali-cli", "ubuntu"]
