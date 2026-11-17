"""FR-08 (B9): timezone-aware UTC "now" and the event type indexes.

The PostgreSQL ``EXPLAIN`` Accept line is an operator gate (needs a PostgreSQL
server); here SQLite's planner is checked for the same two query shapes, plus a
DST-boundary unit test for the time helper.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import timeutil

pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

_ORCH = Path(__file__).resolve().parent.parent / "cyber-range" / "services" / "scenario-orchestrator"


@pytest.fixture()
def rome_tz():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Rome"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def test_dst_fall_back_instants_stay_distinct_and_ordered(rome_tz):
    # 2026-10-25: Rome falls back 03:00 CEST -> 02:00 CET. 00:30Z and 01:30Z are both
    # 02:30 local wall time; naive local time collides, UTC does not.
    first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    second = first + timedelta(hours=1)
    local = [i.astimezone().replace(tzinfo=None) for i in (first, second)]
    assert local[0] == local[1]  # the B9 defect with naive local "now"
    stored = [timeutil.to_db(i) for i in (first, second)]
    assert stored[0] < stored[1] and stored[1] - stored[0] == timedelta(hours=1)
    assert [timeutil.from_db(s) for s in stored] == [first, second]


def test_spring_forward_gap(rome_tz):
    # 2026-03-29 02:00 CET -> 03:00 CEST: 01:59Z and 02:01Z are two minutes apart.
    a = datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc)
    b = datetime(2026, 3, 29, 1, 1, tzinfo=timezone.utc)
    assert timeutil.to_db(b) - timeutil.to_db(a) == timedelta(minutes=2)


def test_db_now_is_utc_regardless_of_host_zone(rome_tz):
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    value = timeutil.db_now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert value.tzinfo is None and before <= value <= after
    assert timeutil.utcnow().tzinfo is timezone.utc


def test_database_module_has_no_naive_local_now():
    source = (_ORCH / "database.py").read_text()
    assert "datetime.now()" not in source


def _upgrade(url, rev="head"):
    cfg = Config(str(_ORCH / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ORCH / "migrations"))
    command.upgrade(cfg, rev)


def test_migration_0011_creates_event_indexes_and_planner_uses_them(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    _upgrade(url)
    engine = create_engine(url)
    names = {ix["name"]: ix["column_names"] for ix in inspect(engine).get_indexes("events")}
    assert names["ix_events_lab_type_id"] == ["lab_id", "type", "id"]
    assert names["ix_events_type_id"] == ["type", "id"]
    with engine.connect() as conn:
        session_list = conn.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM events WHERE lab_id='a' AND type='agent_session'"
            " ORDER BY id DESC LIMIT 50")).fetchall()
        lost = conn.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM events WHERE type='source_review_capture'"
            " ORDER BY id")).fetchall()
    assert "ix_events_lab_type_id" in " ".join(str(r) for r in session_list)
    assert "ix_events_type_id" in " ".join(str(r) for r in lost)
