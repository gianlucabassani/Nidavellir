"""OBS-01 (FR-10, ADR-0018): the span model.

One row per action with digests, redacted previews and a stored visibility.
An agent key reads only agent-visible spans of an arena it is bound to.
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

import spans
from database import Database
from tests.research_support import active_arena, bind, client

# Built at runtime so no token-shaped literal is committed (the Guard scans for them).
_B64 = "".join(chr(c) for c in range(97, 123))
JWT = ".".join(["eyJ" + _B64[:20], "eyJ" + _B64[3:25], _B64[5:26]])
BEARER = "Bearer " + _B64[:16] + "0123456789"
COOKIE = "session=" + "s3cr3t" + "-cookie-value; theme=dark"
SECRETS = (JWT, _B64[:16] + "0123456789", "s3cr3t-cookie-value")


def test_previews_never_hold_a_bearer_token_cookie_or_jwt():
    request = {"method": "GET", "path": "/admin",
               "headers": {"Authorization": BEARER, "Cookie": COOKIE, "X-Trace": "ok"},
               "body": f"token in prose {JWT}"}
    raw = (f"GET / HTTP/1.1\nAuthorization: {BEARER}\nCookie: {COOKIE}\n"
           f"Set-Cookie: {COOKIE}\n\nsee {JWT} and {BEARER}")
    for value in (request, raw, [request]):
        preview = spans.redact_preview(value)
        assert not any(secret in preview for secret in SECRETS), preview
    assert "X-Trace" in spans.redact_preview(request)
    assert len(spans.redact_preview("x" * 10000)) <= spans.PREVIEW_LIMIT


def test_build_digests_the_full_payload_and_bounds_the_preview():
    big = {"body": "y" * 9000}
    row = spans.build(name="http/request", kind="tool", actor="a", actor_kind="agent",
                      arena_id="arena-1", input=big, output={"status": 200})
    assert row["input_digest"] == spans.digest(big)
    assert row["input_digest"] != spans.digest({"body": "y" * 8999})
    assert len(row["input_preview"]) <= spans.PREVIEW_LIMIT
    assert row["trace_id"] == spans.trace_id_for(arena_id="arena-1")
    assert len(row["trace_id"]) == 32 and len(row["span_id"]) == 16
    trial = spans.build(name="t", kind="tool", actor="a", actor_kind="agent",
                        arena_id="arena-1", trial_id="trial-9")
    assert trial["trace_id"] == spans.trace_id_for(trial_id="trial-9")


def test_validation_spans_are_always_operator_only_and_values_are_checked():
    row = spans.build(name="validator", kind="validation", actor="worker",
                      actor_kind="system", visibility="agent")
    assert row["visibility"] == "operator"
    for bad in ({"kind": "magic"}, {"status": "maybe"}, {"actor_kind": "robot"},
                {"visibility": "public"}):
        fields = {"name": "x", "kind": "tool", "actor": "a", "actor_kind": "agent", **bad}
        with pytest.raises(ValueError):
            spans.build(**fields)


def test_repository_round_trip_ordering_and_filters():
    db = Database()
    arena = f"obs01-{uuid.uuid4().hex[:8]}"
    t0 = datetime.now(timezone.utc)
    first = spans.record(db, name="exec", kind="tool", actor="agent-1", actor_kind="agent",
                         arena_id=arena, started_at=t0, ended_at=t0 + timedelta(milliseconds=250),
                         input={"command": "id"}, output={"exit_code": 0},
                         attrs={"gen_ai.operation.name": "execute_tool", "api_key": "hide-me"})
    second = spans.record(db, name="validate", kind="validation", actor="worker",
                          actor_kind="system", arena_id=arena, status="error",
                          error_class="Timeout")
    rows = db.list_spans(arena_id=arena)
    assert [r["id"] for r in rows] == [first, second]
    assert rows[0]["duration_ms"] == 250 and rows[0]["status"] == "ok"
    assert rows[0]["attrs"]["gen_ai.operation.name"] == "execute_tool"
    assert rows[0]["attrs"]["api_key"] != "hide-me"
    assert rows[1]["visibility"] == "operator" and rows[1]["error_class"] == "Timeout"
    assert [r["id"] for r in db.list_spans(arena_id=arena, after_id=first)] == [second]
    assert [r["id"] for r in db.list_spans(arena_id=arena, visibility=("agent",))] == [first]


def test_a_failed_write_never_fails_the_action():
    class Broken:
        def insert_span(self, row):
            raise RuntimeError("database down")
    assert spans.record(Broken(), name="x", kind="tool", actor="a", actor_kind="agent") is None


def test_agent_keys_read_only_agent_spans_of_bound_arenas():
    db = Database()
    operator, agent = client("operator"), client("agent")
    arena, other = active_arena(), active_arena()
    bind(operator, arena, agent, "attacker")
    spans.record(db, name="exec", kind="tool", actor=agent.name, actor_kind="agent",
                 arena_id=arena)
    spans.record(db, name="validate", kind="validation", actor="worker",
                 actor_kind="system", arena_id=arena)
    spans.record(db, name="truth", kind="lifecycle", actor="worker", actor_kind="system",
                 arena_id=arena, visibility="operator")

    seen = operator.get(f"/arenas/{arena}/spans").json()["spans"]
    assert [s["name"] for s in seen] == ["exec", "validate", "truth"]
    mine = agent.get(f"/arenas/{arena}/spans")
    assert mine.status_code == 200
    assert [s["name"] for s in mine.json()["spans"]] == ["exec"]
    assert agent.get(f"/arenas/{other}/spans").status_code == 403
    assert operator.get("/arenas/missing/spans").status_code == 404
    page = operator.get(f"/arenas/{arena}/spans", params={"limit": 1}).json()
    rest = operator.get(f"/arenas/{arena}/spans",
                        params={"after_id": page["next_after_id"]}).json()["spans"]
    assert [s["name"] for s in rest] == ["validate", "truth"]


def test_migration_0012_creates_the_spans_table(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    orch = Path(__file__).resolve().parents[1] / "cyber-range" / "services" / "scenario-orchestrator"
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(orch / "alembic.ini"))
    cfg.set_main_option("script_location", str(orch / "migrations"))
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(url))
    columns = {c["name"] for c in insp.get_columns("spans")}
    assert {"span_id", "trace_id", "parent_span_id", "visibility", "input_digest",
            "output_preview", "attrs", "duration_ms"} <= columns
    assert {ix["name"] for ix in insp.get_indexes("spans")} >= {
        "ix_spans_arena_id_id", "ix_spans_trace_id", "ix_spans_trial_id"}
    command.downgrade(cfg, "0011")
    assert "spans" not in inspect(create_engine(url)).get_table_names()
