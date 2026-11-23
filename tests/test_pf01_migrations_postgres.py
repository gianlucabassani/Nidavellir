"""
PF-01 U4 (review 2026-11-16): column migrations on an old schema.

FR-01 proved and fixed U4 on SQLite (``tests/test_fr01_migrations.py``): the old
start-up ``create_all`` never added a later revision's column, and the deploy-time
``migrate`` step now upgrades or adopts the database. Production runs PostgreSQL,
where ``ALTER TABLE`` and types behave differently, so these tests repeat the
upgrade on PostgreSQL with rows in place: from every historical revision, and from
an unversioned (create_all-built) database. Each test uses its own scratch
database, so the suite's database is never touched.
"""
import os
import uuid
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL migration path")

pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

import migrate  # noqa: E402

REVISIONS = ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009",
             "0010"]


@contextmanager
def _scratch_database(monkeypatch):
    base = make_url(os.environ["DATABASE_URL"])
    name = f"pf01_u4_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": name})
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def _seed(url):
    """A deployment and its event, written with only the baseline columns."""
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO deployments (id, user_id, scenario, status, created_at, updated_at) "
            "VALUES ('dep-1', 'u', 'custom', 'active', now(), now())"))
        conn.execute(text(
            "INSERT INTO events (lab_id, ts, actor, type, payload) "
            "VALUES ('dep-1', now(), 'test', 'state', '{\"to\": \"active\"}')"))
    engine.dispose()


def _assert_at_head_with_data(url):
    engine = create_engine(url)
    try:
        assert migrate.current_revision(engine) == migrate.head_revision()
        migrate.verify_matches_models(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT status FROM deployments WHERE id='dep-1'")
                                ).scalar_one() == "active"
            assert conn.execute(text("SELECT count(*) FROM events WHERE lab_id='dep-1'")
                                ).scalar_one() == 1
        names = {ix["name"] for ix in inspect(engine).get_indexes("events")}
        assert {"ix_events_lab_type_id", "ix_events_type_id"} <= names
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", REVISIONS)
def test_every_historical_revision_upgrades_to_head_with_rows_in_place(monkeypatch, revision):
    with _scratch_database(monkeypatch) as url:
        command.upgrade(migrate._alembic_config(url), "0001")
        _seed(url)
        command.upgrade(migrate._alembic_config(url), revision)
        actions = migrate.migrate(url)
        assert actions == [f"upgrade {revision} -> {migrate.head_revision()}"]
        _assert_at_head_with_data(url)


def test_an_unversioned_create_all_database_is_adopted_with_rows_in_place(monkeypatch):
    with _scratch_database(monkeypatch) as url:
        command.upgrade(migrate._alembic_config(url), "0001")
        _seed(url)
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE alembic_version"))
        engine.dispose()
        actions = migrate.migrate(url)
        assert "add column deployments.expires_at" in actions
        assert actions[-1] == f"stamp {migrate.head_revision()}"
        _assert_at_head_with_data(url)
        assert migrate.migrate(url) == [
            f"upgrade {migrate.head_revision()} -> {migrate.head_revision()}"]
