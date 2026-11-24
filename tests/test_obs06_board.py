"""OBS-06: the cross-arena board and its attention inbox."""
import time

import spans
import streams
from database import Database
from tests.research_support import active_arena, bind, client


def test_board_lists_live_arenas_with_agent_last_action_error_rate_and_budget():
    db = Database()
    operator, agent = client("operator"), client("agent")
    arena = active_arena()
    bind(operator, arena, agent, "attacker")
    for status in ("ok", "ok", "error", "ok"):
        spans.record(db, name="exec", kind="tool", actor=agent.name, actor_kind="agent",
                     arena_id=arena, status=status)
    spans.record(db, name="validate", kind="validation", actor="worker",
                 actor_kind="system", arena_id=arena, status="error")
    board = operator.get("/board").json()
    row = next(a for a in board["arenas"] if a["id"] == arena)
    assert row["agents"] == [{"name": agent.name, "stance": "attacker", "paused": False}]
    assert row["last_action"]["name"] == "exec" and row["last_action"]["actor"] == agent.name
    assert row["recent_actions"] == 4 and row["error_rate"] == 0.25  # validation excluded
    assert row["budget"]["cap"] and row["budget"]["stopped"] is False
    assert board["idle_minutes"] > 0
    assert client("agent").get("/board").status_code == 403


def test_inbox_collects_what_needs_a_human():
    db = Database()
    operator = client("operator")
    arena = active_arena()
    db.record_event(arena, "deploy_failed", {"error": "image not found"}, actor="worker")
    db.record_event(arena, "finding_verification", {"verdict": "confirmed"}, actor="op")
    db.record_event(arena, "agent_exec", {"command": "id"}, actor="a")
    spans.record(db, name="exec", kind="tool", actor="a", actor_kind="agent",
                 arena_id=arena, status="budget_refused")
    assert operator.post(f"/arenas/{arena}/stop", json={
        "reason": "operator check", "idempotency_key": "obs06-stop-key"}).status_code == 200
    inbox = [i for i in operator.get("/board").json()["inbox"] if i["arena_id"] == arena]
    kinds = {i["kind"] for i in inbox}
    assert {"arena_failed", "verdict", "budget_exhausted", "stop"} <= kinds
    assert all(i["key"] and i["at"] for i in inbox)
    assert not any("agent_exec" in i["text"] for i in inbox)


def test_board_stream_rebuilds_only_after_activity(monkeypatch):
    monkeypatch.setattr(streams, "KEEPALIVE_SECONDS", 0.05)
    builds = []

    class PubSub:
        def __init__(self):
            self.queue = [None, None, {"type": "message"}]

        def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
            item = self.queue.pop(0) if self.queue else None
            if item is None:
                time.sleep(timeout)
            return item

        def close(self):
            pass

    frames = list(streams.board_frames(lambda: builds.append(1) or {"n": len(builds)},
                                       subscribe=PubSub, max_seconds=0.6, min_interval=0.01))
    assert sum(f.startswith("event: board") for f in frames) == 2 == len(builds)
    assert any(f.startswith(": keepalive") for f in frames)
