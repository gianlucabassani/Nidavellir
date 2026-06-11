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
        data={"username": "admin", "password": "cyberguard", "csrf_token": token},
    )


def test_routes_require_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_rejects_missing_csrf_token(client):
    resp = client.post("/login", data={"username": "admin", "password": "cyberguard"})
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


def test_lobby_separates_destroyed_labs(client, monkeypatch):
    """Destroyed labs must leave the mission list and land in the archive."""
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
    html = client.get("/").data.decode()

    assert "lab-alive" in html
    assert "ARCHIVE" in html and "lab-gone" in html
    # The destroyed lab must not render as a mission card (those carry the
    # status badge layout); it appears only inside the archive collapse.
    archive_idx = html.index("id=\"archive\"")
    assert html.index("lab-gone") > archive_idx


def test_external_redirect_target_is_ignored(client):
    token = _csrf_token(client)
    resp = client.post(
        "/login?next=https://evil.example",
        data={"username": "admin", "password": "cyberguard", "csrf_token": token},
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


def test_lobby_archive_offers_cleanup_controls(client, monkeypatch):
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
    html = client.get("/").data.decode()

    assert "/archive/clear" in html
    assert "/archive/delete/id-2" in html
