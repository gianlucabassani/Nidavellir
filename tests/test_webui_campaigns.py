"""NV-14 slice 3: console proxies for campaigns (session, CSRF, pass-through)."""
import pytest

pytest.importorskip("flask_wtf")

from tests.test_webui import _csrf_token, _login, webui_app  # noqa: E402
from tests.test_webui_source_review import _Upstream, upstream  # noqa: E402, F401

CID = "0123456789abcdef0123456789abcdef"
KEY = "0123456789ab"
DIGEST = "sha256:" + "a" * 64
BASE = "/api/console/research/campaigns"


@pytest.fixture()
def client():
    webui_app.config["TESTING"] = True
    return webui_app.test_client()


def test_campaign_pages_and_projections_require_login(client, upstream):  # noqa: F811
    for path in ("/console/research/campaigns", f"/console/research/campaigns/{CID}", BASE,
                 f"{BASE}/{CID}", f"{BASE}/{CID}/bundles/{DIGEST}"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
    assert upstream.calls == []


def test_console_shell_serves_the_campaign_routes(client):
    _login(client)
    for path in ("/console/research/campaigns", f"/console/research/campaigns/{CID}"):
        assert client.get(path).status_code in (200, 503)  # 503: assets not built here


def test_writes_require_session_and_csrf(client, upstream):  # noqa: F811
    writes = (
        (BASE, {"name": "n", "product": "p"}),
        (f"{BASE}/{CID}/findings", {"finding_id": KEY}),
        (f"{BASE}/{CID}/findings/{KEY}/disclosure", {"state": "reported"}),
        (f"{BASE}/{CID}/findings/{KEY}/bundles", {"include_poc": False}))
    for path, body in writes:  # no session
        assert client.post(path, json=body).status_code in (302, 400), path
    token = _csrf_token(client)
    _login(client)
    for path, body in writes:  # session, no or wrong token
        assert client.post(path, json=body).status_code == 400, path
        assert client.post(path, json=body, headers={"X-CSRFToken": "wrong"}).status_code == 400
    assert upstream.calls == []

    headers = {"X-CSRFToken": token}
    for path, _ in writes:
        assert client.post(path, data="not json", headers=headers).status_code == 422, path
        assert client.post(path, json=["list"], headers=headers).status_code == 422, path
    assert upstream.calls == []
    upstream.status = 201
    for path, body in writes:
        assert client.post(path, json=body, headers=headers).status_code == 201, path
    assert upstream.calls == [
        ("POST", "http://orch/research/campaigns", None, writes[0][1]),
        ("POST", f"http://orch/research/campaigns/{CID}/findings", None, writes[1][1]),
        ("POST", f"http://orch/research/campaigns/{CID}/findings/{KEY}/disclosure", None,
         writes[2][1]),
        ("POST", f"http://orch/research/campaigns/{CID}/findings/{KEY}/bundles", None,
         writes[3][1])]


def test_reads_forward_only_known_parameters(client, upstream):  # noqa: F811
    _login(client)
    assert client.get(f"{BASE}?before=7&limit=5&evil=1").status_code == 200
    assert client.get(f"{BASE}/{CID}?anything=1").status_code == 200
    assert upstream.calls == [
        ("GET", "http://orch/research/campaigns", {"before": "7", "limit": "5"}, None),
        ("GET", f"http://orch/research/campaigns/{CID}", None, None)]


def test_bundle_file_is_passed_through_byte_for_byte(client, monkeypatch):
    """The console must not re-serialise a bundle: its SHA-256 is its digest."""
    import hashlib
    import types

    import app as webui_module

    body = '{"schema":"nidavellir/disclosure-bundle/v1","title":"«café»"}'.encode()
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    calls = []

    def upstream_file(method, url, headers=None, timeout=None, **kwargs):
        calls.append((method, url))
        return types.SimpleNamespace(status_code=200, content=body, json=lambda: {})

    monkeypatch.setattr(webui_module.requests, "request", upstream_file)
    monkeypatch.setattr(webui_module, "API_URL", "http://orch")
    _login(client)
    response = client.get(f"{BASE}/{CID}/bundles/{digest}")
    assert response.status_code == 200 and response.data == body
    assert response.headers["X-Bundle-Digest"] == digest
    assert calls == [("GET", f"http://orch/research/campaigns/{CID}/bundles/{digest}")]
    # Bytes that do not match the digest asked for are refused, not handed on.
    other = "sha256:" + "a" * 64
    assert client.get(f"{BASE}/{CID}/bundles/{other}").status_code == 502


@pytest.mark.parametrize("path", [
    f"{BASE}/not-a-campaign", f"{BASE}/{CID.upper()}", f"{BASE}/{CID}0",
    f"{BASE}/{CID}/bundles/not-a-digest", f"{BASE}/{CID}/bundles/sha256:abc",
    f"{BASE}/{CID}/bundles/{DIGEST}0", f"{BASE}/..%2F..%2Fdeployments"])
def test_malformed_ids_never_reach_the_service(client, upstream, path):  # noqa: F811
    _login(client)
    assert client.get(path).status_code == 404
    assert upstream.calls == []


def test_malformed_ids_are_refused_on_write(client, upstream):  # noqa: F811
    token = _csrf_token(client)
    _login(client)
    headers = {"X-CSRFToken": token}
    for path in (f"{BASE}/nope/findings", f"{BASE}/{CID}/findings/nope/disclosure",
                 f"{BASE}/{CID}/findings/{KEY}0/bundles",
                 f"{BASE}/{CID}/findings/..%2Fx/disclosure"):
        assert client.post(path, json={"state": "reported"}, headers=headers).status_code == 404
    assert upstream.calls == []


@pytest.mark.parametrize("status,detail,expected", [
    (409, "disclosure bundle integrity check failed", "disclosure bundle integrity check failed"),
    (404, "campaign was not found", "campaign was not found"),
    (403, "operator or admin role required", "operator or admin role required"),
    (422, "regressed needs a note of at least 10 characters",
     "regressed needs a note of at least 10 characters"),
])
def test_service_errors_keep_their_status_and_message(client, upstream, status, detail,  # noqa: F811
                                                      expected):
    _login(client)
    upstream.status, upstream.body = status, {"detail": detail}
    response = client.get(f"{BASE}/{CID}")
    assert response.status_code == status
    assert response.get_json() == {"error": expected}


def test_unreachable_or_malformed_service_is_an_error_not_an_empty_page(client, monkeypatch):
    import app as webui_module

    _login(client)

    def down(*args, **kwargs):
        raise webui_module.requests.ConnectionError("refused")

    monkeypatch.setattr(webui_module.requests, "request", down)
    response = client.get(f"{BASE}/{CID}")
    assert response.status_code == 502
    assert response.get_json()["error"].startswith("Campaigns is unavailable")
    monkeypatch.setattr(webui_module.requests, "request", _Upstream(200, ["not", "an", "object"]))
    assert client.get(f"{BASE}/{CID}").status_code == 502


def test_console_reaches_the_real_routes_end_to_end(client, monkeypatch, tmp_path):
    """Console proxy -> real service: create, add a pair, disclose, bundle, read back."""
    import app as webui_module
    import config
    from database import Database
    from tests.test_campaign_bundles import SECRET_TOKEN, _evidenced_pair
    from tests.test_campaigns import _client as service_client

    monkeypatch.setattr(config, "DISCLOSURE_BUNDLES_DIR", tmp_path / "bundles")
    service = service_client("operator")

    def forward(method, url, params=None, json=None, headers=None, timeout=None):
        return service.request(method, url.removeprefix("http://orch"), params=params, json=json)

    monkeypatch.setattr(webui_module.requests, "request", forward)
    monkeypatch.setattr(webui_module, "API_URL", "http://orch")
    token = _csrf_token(client)
    _login(client)
    headers = {"X-CSRFToken": token}
    root, variant, _ = _evidenced_pair(Database())

    created = client.post(BASE, json={"name": "Console campaign", "product": "vaultwarden"},
                          headers=headers)
    assert created.status_code == 201, created.get_json()
    cid = created.get_json()["campaign_id"]
    assert client.get(BASE).get_json()["campaigns"][0]["campaign_id"] == cid
    added = client.post(f"{BASE}/{cid}/findings", json={"finding_id": variant}, headers=headers)
    assert added.status_code == 200 and added.get_json()["research_key"] == root
    repeat = client.post(f"{BASE}/{cid}/findings", json={"finding_id": root}, headers=headers)
    assert repeat.get_json()["added"] is False
    refused = client.post(f"{BASE}/{cid}/findings/{root}/disclosure",
                          json={"state": "regressed"}, headers=headers)
    assert refused.status_code == 422 and "at least 10" in refused.get_json()["error"]
    saved = client.post(f"{BASE}/{cid}/findings/{root}/disclosure",
                        json={"state": "fixed", "reference": "GHSA-demo"}, headers=headers)
    row = saved.get_json()["findings"][0]
    assert row["disclosure"]["state"] == "fixed" and row["state_supported_by_evidence"] is True
    bundle = client.post(f"{BASE}/{cid}/findings/{root}/bundles", json={}, headers=headers)
    assert bundle.status_code == 201
    digest = bundle.get_json()["bundle_digest"]
    read = client.get(f"{BASE}/{cid}/bundles/{digest}")
    assert read.status_code == 200 and read.get_json() == bundle.get_json()["bundle"]
    import hashlib
    assert "sha256:" + hashlib.sha256(read.data).hexdigest() == digest
    assert SECRET_TOKEN not in read.get_data(as_text=True)
    summary = client.get(f"{BASE}/{cid}").get_json()
    assert summary["findings"][0]["bundles"][0]["bundle_digest"] == digest
    assert client.get(f"{BASE}/{'0' * 32}").status_code == 404
