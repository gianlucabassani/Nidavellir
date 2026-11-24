"""UX-06: evidence is picked from the arena's own records, not pasted.

The console lists the arena's captured HTTP transactions and evidence
artifacts from its audit events, de-duplicated, with no request bodies.
"""
import pytest

pytest.importorskip("flask_wtf")

from tests.test_webui import _login, client  # noqa: E402,F401

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def test_candidates_list_transactions_and_artifacts_without_bodies(client, monkeypatch):  # noqa: F811
    import app as webui_module

    assert _login(client).status_code == 302
    calls = []

    def fake(path):
        calls.append(path)
        if "type=http_request" in path:
            return {"events": [
                {"ts": "t2", "actor": "op", "payload": {
                    "method": "GET", "path": "/admin", "status": 403, "node": "victim",
                    "transaction_digest": D1, "body": "secret-body"}},
                {"ts": "t1", "actor": "op", "payload": {"transaction_digest": D1}},
            ]}, True
        return {"events": [{"ts": "t3", "actor": "op", "payload": {
            "digest": D2, "kind": "workspace_diff", "node": "kali", "bytes": 42}}]}, True

    monkeypatch.setattr(webui_module, "_api_get", fake)
    response = client.get("/api/console/arenas/arena-1/evidence-candidates")
    assert response.status_code == 200
    data = response.get_json()
    assert data["transactions"] == [{"digest": D1, "method": "GET", "path": "/admin",
                                     "status": 403, "node": "victim", "ts": "t2", "actor": "op"}]
    assert data["artifacts"][0]["digest"] == D2 and data["artifacts"][0]["bytes"] == 42
    assert "secret-body" not in response.get_data(as_text=True)
    assert all(path.startswith("/deployments/arena-1/events") for path in calls)


def test_candidates_unavailable_is_an_error_not_an_empty_list(client, monkeypatch):  # noqa: F811
    import app as webui_module

    assert _login(client).status_code == 302
    monkeypatch.setattr(webui_module, "_api_get", lambda _path: (None, False))
    assert client.get("/api/console/arenas/a/evidence-candidates").status_code == 503
