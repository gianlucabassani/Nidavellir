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
    import spans as _spans  # noqa: F401 - the action middleware records spans

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
