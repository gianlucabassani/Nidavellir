"""UX-13: tools of the job — node log tail, operator shell, HTTP ledger rows,
global search."""
from __future__ import annotations

import api
from database import Database
from providers.docker_local import DockerLocalProvider
from providers.mock import MockProvider
from tests.research_support import active_arena, client


# --- node log tail ------------------------------------------------------------


def test_node_logs_are_operator_only_bounded_redacted_and_audited_once(monkeypatch):
    secret = "pass" + "word=" + "hunter" + "2value"
    calls = []

    def fake(self, instance_id, node, *, tail=200, since=None):
        calls.append((node, tail, since))
        return {"success": True, "lines": [
            {"ts": f"2026-11-25T10:00:0{i}Z", "text": f"line {i}"} for i in range(5)
        ] + [{"ts": "2026-11-25T10:00:09Z", "text": f"boot {secret}"}]}

    monkeypatch.setattr(api.Orchestrator, "node_logs", fake)
    arena = active_arena()
    operator = client("operator")
    first = operator.get(f"/arenas/{arena}/nodes/victim/logs", params={"tail": 3})
    assert first.status_code == 200
    lines = first.json()["lines"]
    assert len(lines) == 3 and "hunter2value" not in lines[-1]["text"]
    follow = operator.get(f"/arenas/{arena}/nodes/victim/logs",
                          params={"tail": 3, "since": 1764064809})
    assert follow.status_code == 200
    assert calls[-1] == ("victim", 3, 1764064809)
    audits = Database().list_events(arena, limit=10, types=["node_logs_read"])
    assert len(audits) == 1 and audits[0]["payload"]["node"] == "victim"
    assert operator.get(f"/arenas/{arena}/nodes/ghost/logs").status_code == 404
    assert operator.get(f"/arenas/{arena}/nodes/victim/logs",
                        params={"tail": 5000}).status_code == 422
    assert client("agent").get(f"/arenas/{arena}/nodes/victim/logs").status_code == 403


def test_node_logs_need_an_active_arena():
    arena = active_arena()
    Database().update_deployment(arena, status="destroying", actor="test")
    assert client("operator").get(
        f"/arenas/{arena}/nodes/victim/logs").status_code == 409


def test_mock_logs_are_labelled_simulated_and_respect_since():
    provider = MockProvider()
    full = provider.node_logs("a", "victim", tail=5)
    assert full["success"] and 0 < len(full["lines"]) <= 5
    assert all("simulated" in line["text"] for line in full["lines"])
    assert provider.node_logs("a", "victim", since=10 ** 10)["lines"] == []


def test_docker_logs_split_timestamps_keep_newest_and_cap_lines():
    class Container:
        def logs(self, **kwargs):
            self.kwargs = kwargs
            return ("\n".join(f"2026-11-25T10:00:0{i}.1Z out {i}" for i in range(6))
                    + "\n2026-11-25T10:00:07Z " + "x" * 9000).encode()

    container = Container()
    provider = DockerLocalProvider.__new__(DockerLocalProvider)
    provider._find_node_container = lambda *_: container
    result = provider.node_logs("a", "victim", tail=3, since=100.7)
    assert container.kwargs == {"tail": 3, "timestamps": True, "since": 101}
    assert [line["text"][:5] for line in result["lines"]] == ["out 4", "out 5", "xxxxx"]
    assert len(result["lines"][-1]["text"]) == DockerLocalProvider.LOG_LINE_CAP
    provider._find_node_container = lambda *_: None
    assert provider.node_logs("a", "victim")["success"] is False


# --- operator shell -------------------------------------------------------------


def test_each_shell_command_is_an_exec_span_and_an_audit_event():
    arena = active_arena()
    operator = client("operator")
    for command in ("id", "uname -a"):
        response = operator.post(f"/arenas/{arena}/exec",
                                 json={"node": "victim", "command": command})
        assert response.status_code == 200, response.text
    rows = [row for row in Database().list_spans(arena_id=arena) if row["name"] == "exec"]
    assert len(rows) == 2
    assert all(row["actor_kind"] == "human" and row["status"] == "ok" for row in rows)
    assert len(Database().list_events(arena, limit=10, types=["agent_exec"])) == 2


# --- HTTP ledger rows -------------------------------------------------------------


def test_ledger_rows_carry_method_path_status_and_size(monkeypatch, tmp_path):
    import config
    import http_transactions

    monkeypatch.setattr(config, "HTTP_TRANSACTIONS_DIR", tmp_path / "tx")
    http_transactions.record("arena-x", request={
        "node": "victim", "method": "POST", "path": "/login", "params": {},
        "headers": {}, "body": "u=a"}, response={"status": 302, "body_bytes": 0})
    stored = http_transactions.record("arena-x", request={
        "node": "victim", "method": "GET", "path": "/admin", "params": {},
        "headers": {}, "body": None}, response={"status": 403, "body_bytes": 1536},
        elapsed_ms=12)
    rows = http_transactions.list_transactions("arena-x")["transactions"]
    summaries = {row["digest"]: row["summary"] for row in rows}
    assert summaries[stored["digest"]] == {"method": "GET", "path": "/admin",
        "node": "victim", "status": 403, "response_bytes": 1536}
    # A tampered envelope fails verification: no summary, row still listed.
    payload = next((tmp_path / "tx").rglob("transaction.json"))
    payload.write_text("{}")
    rows = http_transactions.list_transactions("arena-x")["transactions"]
    assert len(rows) == 2 and sum(row["summary"] is None for row in rows) == 1


# --- global search ------------------------------------------------------------------


def _seed_search():
    import spans

    db = Database()
    arena = active_arena("search-scenario")
    tx = "sha256:" + "c0ffee" + "1" * 58
    db.record_event(arena, "http_request", {"method": "GET", "path": "/admin/users",
                    "status": 403, "transaction_digest": tx}, actor="op")
    db.record_event(arena, "finding", {"finding_id": "fid-1",
                    "title": "Stored XSS in profile bio"}, actor="agent")
    spans.record(db, name="http/request", kind="tool", actor="op", actor_kind="human",
                 arena_id=arena, input={"url": "/admin/users"},
                 attrs={"nv.transaction_digest": tx})
    return arena, tx


def test_search_finds_text_across_findings_transactions_spans_and_arenas():
    arena, tx = _seed_search()
    operator = client("operator")
    found = operator.get("/search", params={"q": "stored xss"}).json()
    assert found["mode"] == "text"
    assert any(f["arena_id"] == arena and f["title"].startswith("Stored XSS")
               for f in found["findings"])
    found = operator.get("/search", params={"q": "admin users"}).json()
    assert any(t["digest"] == tx for t in found["transactions"])
    assert any(s["arena_id"] == arena for s in found["spans"])
    assert any(a["id"] == arena for a in
               operator.get("/search", params={"q": "search-scen"}).json()["arenas"])


def test_search_by_digest_prefix_with_or_without_scheme():
    arena, tx = _seed_search()
    operator = client("operator")
    for q in (tx[:20], tx[7:20]):
        found = operator.get("/search", params={"q": q}).json()
        assert found["mode"] == "digest"
        assert any(t["digest"] == tx and t["arena_id"] == arena for t in found["transactions"])
        assert any(s["arena_id"] == arena for s in found["spans"])
    assert any(a["id"] == arena for a in
               operator.get("/search", params={"q": arena[:8]}).json()["arenas"])


def test_search_is_operator_only_bounded_and_treats_wildcards_literally():
    operator = client("operator")
    assert client("agent").get("/search", params={"q": "admin"}).status_code == 403
    assert operator.get("/search", params={"q": "a"}).status_code == 422
    assert operator.get("/search", params={"q": "x" * 201}).status_code == 422
    assert operator.get("/search", params={"q": "%%"}).json()["mode"] == "none"
    found = operator.get("/search", params={"q": "100%_match"}).json()
    assert found["mode"] == "text"
    assert all(len(found[k]) <= 10 for k in ("arenas", "findings", "transactions", "spans"))
