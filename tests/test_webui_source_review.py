"""UI-R4 slice 4: console proxies for source review (session, CSRF, pass-through)."""
import types

import pytest

pytest.importorskip("flask_wtf")

from tests.test_webui import _csrf_token, _login, webui_app  # noqa: E402

SID = "0123456789abcdef0123456789abcdef"
KEY = "a" * 64
BASE = "/api/console/research/review-sessions"


@pytest.fixture()
def client():
    webui_app.config["TESTING"] = True
    return webui_app.test_client()


class _Upstream:
    """Records what the console sends to the service and replays a canned answer."""

    def __init__(self, status=200, body=None):
        self.calls, self.status, self.body = [], status, {"ok": True} if body is None else body

    def __call__(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append((method, url, params, json))
        assert headers and "X-API-Key" in headers
        return types.SimpleNamespace(status_code=self.status, json=lambda: self.body)


@pytest.fixture()
def upstream(monkeypatch):
    import app as webui_module

    recorder = _Upstream()
    monkeypatch.setattr(webui_module.requests, "request", recorder)
    monkeypatch.setattr(webui_module, "API_URL", "http://orch")
    return recorder


def test_source_review_pages_and_projections_require_login(client, upstream):
    for path in ("/console/research/review", f"/console/research/review/{SID}", BASE,
                 f"{BASE}/{SID}", f"{BASE}/{SID}/sites?pattern=mutation-order",
                 f"{BASE}/{SID}/fix-links/F1", "/api/console/findings/0123456789ab"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
    assert upstream.calls == []


def test_console_shell_serves_the_source_review_routes(client):
    _login(client)
    for path in ("/console/research/review", f"/console/research/review/{SID}"):
        assert client.get(path).status_code in (200, 503)  # 503: assets not built here


def test_writes_require_session_and_csrf(client, upstream):
    review = f"{BASE}/{SID}/sites/{KEY}/review"
    create = {"name": "n", "ref": "HEAD", "patterns": ["mutation-order"]}
    # No session: redirected to login before anything else.
    assert client.post(review, json={"state": "in_review"}).status_code in (302, 400)
    token = _csrf_token(client)
    _login(client)
    # Session but no CSRF token: refused, nothing forwarded.
    assert client.post(review, json={"state": "in_review"}).status_code == 400
    assert client.post(BASE, json=create).status_code == 400
    assert client.post(review, json={"state": "in_review"},
                       headers={"X-CSRFToken": "wrong"}).status_code == 400
    assert upstream.calls == []

    headers = {"X-CSRFToken": token}
    assert client.post(review, data="not json", headers=headers).status_code == 422
    assert client.post(BASE, json=["list"], headers=headers).status_code == 422
    assert upstream.calls == []
    body = {"state": "dismissed", "note": "Filter is by primary key."}
    assert client.post(review, json=body, headers=headers).status_code == 200
    upstream.status = 202
    assert client.post(BASE, json=create, headers=headers).status_code == 202
    assert upstream.calls == [
        ("POST", f"http://orch/research/review-sessions/{SID}/sites/{KEY}/review", None, body),
        ("POST", "http://orch/research/review-sessions", None, create)]


def test_reads_forward_only_known_parameters(client, upstream):
    _login(client)
    assert client.get(f"{BASE}?before=9&limit=5&evil=1").status_code == 200
    assert client.get(f"{BASE}/{SID}").status_code == 200
    assert client.get(f"{BASE}/{SID}/sites?pattern=mutation-order&offset=50&limit=50"
                      "&status=uncovered&classification=c&review_state=dismissed"
                      "&file_prefix=src/&evil=1").status_code == 200
    assert client.get(f"{BASE}/{SID}/fix-links/F12").status_code == 200
    assert client.get("/api/console/findings/0123456789ab").status_code == 200
    root = "http://orch/research/review-sessions"
    assert upstream.calls == [
        ("GET", root, {"before": "9", "limit": "5"}, None),
        ("GET", f"{root}/{SID}", None, None),
        ("GET", f"{root}/{SID}/sites", {
            "pattern": "mutation-order", "offset": "50", "limit": "50", "status": "uncovered",
            "classification": "c", "review_state": "dismissed", "file_prefix": "src/"}, None),
        ("GET", f"{root}/{SID}/fix-links/F12", None, None),
        ("GET", "http://orch/findings/0123456789ab", None, None)]


@pytest.mark.parametrize("path", [
    f"{BASE}/not-a-session", f"{BASE}/{SID.upper()}", f"{BASE}/{SID}x/sites",
    f"{BASE}/{SID}/fix-links/F0", f"{BASE}/{SID}/fix-links/F100",
    f"{BASE}/{SID}/fix-links/..%2Fsites", "/api/console/findings/not-an-id",
    "/api/console/findings/0123456789AB"])
def test_malformed_ids_never_reach_the_service(client, upstream, path):
    _login(client)
    assert client.get(path).status_code == 404
    assert upstream.calls == []


def test_malformed_site_key_is_refused_on_write(client, upstream):
    token = _csrf_token(client)
    _login(client)
    for key in ("short", "A" * 64, "a" * 63):
        response = client.post(f"{BASE}/{SID}/sites/{key}/review", json={"state": "in_review"},
                               headers={"X-CSRFToken": token})
        assert response.status_code == 404
    assert upstream.calls == []


@pytest.mark.parametrize("status,detail,expected", [
    (409, "source review snapshot integrity check failed",
     "source review snapshot integrity check failed"),
    (404, "source review session was not found", "source review session was not found"),
    (403, "operator or admin role required", "operator or admin role required"),
    (422, [{"loc": ["body", "note"], "msg": "too long"}], "note: too long"),
])
def test_service_errors_keep_their_status_and_message(client, upstream, status, detail, expected):
    _login(client)
    upstream.status, upstream.body = status, {"detail": detail}
    response = client.get(f"{BASE}/{SID}")
    assert response.status_code == status
    assert response.get_json() == {"error": expected}


def test_unreachable_or_malformed_service_is_an_error_not_an_empty_page(client, monkeypatch):
    import app as webui_module

    _login(client)

    def down(*args, **kwargs):
        raise webui_module.requests.ConnectionError("refused")

    monkeypatch.setattr(webui_module.requests, "request", down)
    response = client.get(f"{BASE}/{SID}")
    assert response.status_code == 502 and "could not be reached" in response.get_json()["error"]
    monkeypatch.setattr(webui_module.requests, "request", _Upstream(200, ["not", "an", "object"]))
    assert client.get(f"{BASE}/{SID}").status_code == 502


def test_console_reaches_the_real_routes_end_to_end(client, monkeypatch, tmp_path):
    """Console proxy -> real service: create, page, review, reload."""
    import api
    import app as webui_module
    import config
    import source_review
    from database import Database
    from tests.test_source_review import VIEWS, _commit, _git
    from tests.test_source_review_api import _client as service_client

    monkeypatch.setattr(config, "SOURCE_REVIEW_SNAPSHOTS_DIR", tmp_path / "snapshots")
    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-q")
    _commit(root, {"src/documents/views.py": VIEWS}, "init")
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(root))
    monkeypatch.setattr(api, "capture_source_review", types.SimpleNamespace(
        delay=lambda session_id: source_review.run_capture(Database(), session_id)))
    service = service_client("operator")

    def forward(method, url, params=None, json=None, headers=None, timeout=None):
        return service.request(method, url.removeprefix("http://orch"), params=params, json=json)

    monkeypatch.setattr(webui_module.requests, "request", forward)
    monkeypatch.setattr(webui_module, "API_URL", "http://orch")
    token = _csrf_token(client)
    _login(client)
    headers = {"X-CSRFToken": token}

    created = client.post(BASE, json={"name": "Console session", "ref": "HEAD",
                                      "patterns": ["unscoped-queryset"]}, headers=headers)
    assert created.status_code == 202, created.get_json()
    sid = created.get_json()["session_id"]
    assert client.get(BASE).get_json()["sessions"][0]["session_id"] == sid
    page = client.get(f"{BASE}/{sid}/sites?pattern=unscoped-queryset").get_json()
    assert page["pattern_total"] == 2 and page["next_offset"] is None
    key = page["sites"][0]["site_key"]
    refused = client.post(f"{BASE}/{sid}/sites/{key}/review", json={"state": "dismissed"},
                          headers=headers)
    assert refused.status_code == 422 and "at least 10" in refused.get_json()["error"]
    saved = client.post(f"{BASE}/{sid}/sites/{key}/review",
                        json={"state": "dismissed", "note": "Filter is by primary key."},
                        headers=headers)
    assert saved.status_code == 200
    again = client.get(f"{BASE}/{sid}/sites?pattern=unscoped-queryset").get_json()
    assert again["sites"][0]["review"]["state"] == "dismissed"
    assert again["sites"][0]["status"] == page["sites"][0]["status"]
    summary = client.get(f"{BASE}/{sid}").get_json()
    assert summary["patterns"][0]["by_review_state"]["dismissed"] == 1
    assert client.get(f"{BASE}/{'0' * 32}").status_code == 404
