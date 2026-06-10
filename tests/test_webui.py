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


def test_external_redirect_target_is_ignored(client):
    token = _csrf_token(client)
    resp = client.post(
        "/login?next=https://evil.example",
        data={"username": "admin", "password": "cyberguard", "csrf_token": token},
    )
    assert resp.headers["Location"] in ("/", "http://localhost/")
