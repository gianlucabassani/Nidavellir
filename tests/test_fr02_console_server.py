"""FR-02 (B16): console production server, session cookie flags, security headers
with a CSP the React bundle passes, and login throttling.

Live parts (release smoke against gunicorn, a real browser showing no CSP violation)
are operator gates.
"""
import re
from pathlib import Path

import pytest

pytest.importorskip("flask_wtf")
from tests.test_webui import _csrf_token, webui_app  # noqa: E402

import app as webui_module  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client():
    webui_app.config["TESTING"] = True
    webui_module._LOGIN_FAILURES.clear()
    yield webui_app.test_client()
    webui_module._LOGIN_FAILURES.clear()


def _attempt(client, password, username="admin"):
    token = _csrf_token(client)
    return client.post("/login", data={"username": username, "password": password,
                                       "csrf_token": token})


def test_sixth_rapid_failed_login_is_refused(client):
    for _ in range(webui_module.LOGIN_MAX_FAILURES):
        assert _attempt(client, "wrong").status_code == 200
    refused = _attempt(client, "nidavellir")  # even the right password
    assert refused.status_code == 429
    assert not client.get("/console").status_code == 200


def test_throttle_is_per_username_across_sources(client):
    for i in range(webui_module.LOGIN_MAX_FAILURES):
        token = _csrf_token(client)
        client.post("/login", data={"username": "admin", "password": "x", "csrf_token": token},
                    environ_base={"REMOTE_ADDR": f"10.0.0.{i}"})
    token = _csrf_token(client)
    r = client.post("/login", data={"username": "admin", "password": "x", "csrf_token": token},
                    environ_base={"REMOTE_ADDR": "10.9.9.9"})
    assert r.status_code == 429


def test_failures_expire_after_the_window(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(webui_module.time, "time", lambda: now[0])
    for _ in range(webui_module.LOGIN_MAX_FAILURES):
        _attempt(client, "wrong")
    assert _attempt(client, "wrong").status_code == 429
    now[0] += webui_module.LOGIN_WINDOW_SECONDS + 1
    assert _attempt(client, "nidavellir").status_code == 302


def test_session_cookie_flags(client):
    resp = _attempt(client, "nidavellir")
    cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert webui_app.config["PERMANENT_SESSION_LIFETIME"].total_seconds() > 0
    assert webui_app.permanent_session_lifetime == webui_app.config["PERMANENT_SESSION_LIFETIME"]


def test_security_headers_and_strict_console_csp(client):
    _attempt(client, "nidavellir")
    resp = client.get("/console")
    # 503 on a host without the built bundle; the headers apply either way.
    assert resp.status_code in (200, 503)
    csp = resp.headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp and "unsafe-inline" not in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    # The console shell itself passes its own policy: no inline script/style,
    # every script/style is a same-origin file.
    with webui_app.test_request_context("/console"):
        html = webui_module.render_template(
            "console.html", entry={"file": "assets/index.js", "css": ["assets/index.css"]},
            username="admin", simulation_mode=False)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert "<style" not in html and " style=" not in html
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert url.startswith("/"), url


def test_react_bundle_source_needs_no_unsafe_policy():
    src = _ROOT / "cyber-range" / "webui" / "frontend" / "src"
    for path in src.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert "eval(" not in text and "new Function" not in text, path
        assert "dangerouslySetInnerHTML" not in text, path


def test_dockerfile_serves_with_gunicorn_threads():
    dockerfile = (_ROOT / "cyber-range" / "webui" / "Dockerfile").read_text()
    cmd = dockerfile[dockerfile.index("CMD"):]
    assert '"gunicorn"' in cmd and '"gthread"' in cmd and '"--workers", "1"' in cmd
