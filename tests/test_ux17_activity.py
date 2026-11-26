"""UX-17: activity summaries for the arena dashboard and the Research overview.

Spans fold into time buckets by family (HTTP, Shell, Model, Other) with
failures, refusals, submitted findings and budget actually spent; totals by
family and actor; tool-time statistics; the newest steps. Operator-only.
"""
from datetime import datetime, timedelta

import activity
import spans
from database import Database
from timeutil import db_now
from tests.research_support import active_arena, client

T0 = datetime(2026, 11, 26, 10, 0, 0)


def _row(kind, name, status="ok", actor="a1", arena="x", at=0, ms=1000, attrs=None):
    return (kind, name, status, actor, arena, T0 + timedelta(seconds=at), ms, attrs or {})


def test_family_classification():
    assert activity.family("tool", "http/request") == "http"
    assert activity.family("tool", "http/replay") == "http"
    assert activity.family("tool", "exec") == "exec"
    assert activity.family("model", "model.call") == "model"
    assert activity.family("tool", "browser/visit") == "other"
    assert activity.family("tool", "findings") == "other"


def test_bucket_width_is_the_smallest_step_that_fits():
    assert activity.bucket_seconds(600, 24) == 30
    assert activity.bucket_seconds(3600, 12) == 300
    assert activity.bucket_seconds(5 * 86400, 24) == 21600
    assert activity.bucket_seconds(30 * 86400, 24) == 86400


def test_summary_counts_by_bucket_family_actor_and_outcome():
    rows = [
        _row("tool", "http/request", at=10, ms=200, attrs={"nv.budget_outcome": "spent"}),
        _row("tool", "http/request", status="error", at=20, ms=400,
             attrs={"nv.budget_outcome": "released"}),
        _row("tool", "exec", at=70, ms=24000, attrs='{"nv.budget_outcome": "spent"}'),
        _row("model", "model.call", at=75, ms=3000, actor="a2"),
        _row("tool", "findings", at=80, ms=100, attrs={"nv.budget_outcome": "spent"}),
        _row("tool", "exec", status="budget_refused", at=130),
        _row("tool", "http/request", at=10_000),  # outside the window
    ]
    out = activity.summarize(rows, start=T0, end=T0 + timedelta(minutes=3), max_buckets=6)
    assert out["bucket_seconds"] == 30
    assert len(out["buckets"]) == 6
    first, third, fifth = out["buckets"][0], out["buckets"][2], out["buckets"][4]
    assert (first["http"], first["failed"], first["spent"]) == (2, 1, 1)
    assert (third["exec"], third["model"], third["other"], third["findings"], third["spent"]) == (
        1, 1, 1, 1, 2)
    assert (fifth["refused"], fifth["exec"]) == (1, 0)
    totals = out["totals"]
    assert totals["by_family"] == {"http": 2, "exec": 1, "model": 1, "other": 1}
    assert totals["failed_by_family"]["http"] == 1
    assert (totals["actions"], totals["failed"], totals["refused"]) == (5, 1, 1)
    actors = {a["actor"]: a for a in out["by_actor"]}
    assert actors["a1"]["actions"] == 4 and actors["a1"]["refused"] == 1
    assert actors["a2"]["model_calls"] == 1 and actors["a2"]["actions"] == 0
    # Tool time only: model calls do not count toward tool durations.
    assert out["durations"]["slowest"] == {"name": "exec", "ms": 24000}
    # Tool durations sorted [100, 200, 400, 24000]: the median is (200 + 400) / 2.
    assert out["durations"]["median_ms"] == 300.0


def test_median_of_even_and_empty_inputs():
    assert activity._median([]) is None
    assert activity._median([100, 200, 400, 24000]) == 300.0
    assert activity._median([5, 1, 3]) == 3.0


def test_empty_window_has_buckets_and_no_statistics():
    out = activity.summarize([], start=T0, end=T0, max_buckets=24)
    assert len(out["buckets"]) == 1
    assert out["totals"]["actions"] == 0
    assert out["durations"] == {"median_ms": None, "slowest": None}


def _seed(arena):
    db = Database()
    # After the arena was created, so inside its window.
    now = db_now()
    spans.record(db, name="http/request", kind="tool", actor="claude", actor_kind="agent",
                 arena_id=arena, input={"path": "/rest/basket/2"},
                 attrs={"nv.budget_outcome": "spent"},
                 started_at=now, ended_at=now + timedelta(seconds=1))
    spans.record(db, name="exec", kind="tool", actor="claude", actor_kind="agent",
                 arena_id=arena, status="error", input={"cmd": "sqlmap -u x"},
                 started_at=now, ended_at=now + timedelta(seconds=10))
    spans.record(db, name="model.call", kind="model", actor="claude", actor_kind="agent",
                 arena_id=arena, started_at=now)
    spans.record(db, name="deploy", kind="lifecycle", actor="system", actor_kind="system",
                 arena_id=arena)


def test_arena_activity_route_summarises_its_spans_and_newest_steps():
    arena = active_arena("ux17-scenario")
    _seed(arena)
    operator = client("operator")
    out = operator.get(f"/arenas/{arena}/activity").json()
    assert out["totals"]["by_family"] == {"http": 1, "exec": 1, "model": 1, "other": 0}
    assert out["totals"]["failed"] == 1
    assert sum(b["spent"] for b in out["buckets"]) == 1
    assert len(out["buckets"]) <= 24
    names = [step["name"] for step in out["recent"]]
    assert names == ["model.call", "exec", "http/request"]  # newest first, no lifecycle
    assert out["recent"][1]["status"] == "error"
    assert "sqlmap" in (out["recent"][1]["preview"] or "")


def test_activity_routes_are_operator_only_and_404_for_unknown_arenas():
    arena = active_arena("ux17-scenario")
    agent = client("agent")
    assert agent.get(f"/arenas/{arena}/activity").status_code == 403
    assert agent.get("/activity/recent").status_code == 403
    operator = client("operator")
    assert operator.get("/arenas/no-such-arena/activity").status_code == 404
    assert operator.get("/activity/recent", params={"minutes": 1}).status_code == 422


def test_recent_activity_covers_every_arena_in_the_window():
    first, second = active_arena("ux17-a"), active_arena("ux17-b")
    _seed(first)
    _seed(second)
    out = client("operator").get("/activity/recent", params={"minutes": 60}).json()
    arenas = {a["arena_id"] for a in out["by_actor"]}
    assert {first, second} <= arenas
    assert out["totals"]["by_family"]["http"] >= 2
    assert len(out["buckets"]) <= 12
