"""
Alembic migration tests (ADR-0004).

`upgrade head` on a scratch database must produce the same schema the app
expects (and that models.py declares) — this is what CI runs so migrations
can't drift from the models.
"""
from pathlib import Path

import pytest

pytest.importorskip("alembic")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

_ORCH = (
    Path(__file__).resolve().parent.parent
    / "cyber-range"
    / "services"
    / "scenario-orchestrator"
)


def _upgrade_head(url):
    cfg = Config(str(_ORCH / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ORCH / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)  # informational; env.py uses env var
    command.upgrade(cfg, "head")


def test_upgrade_head_builds_full_schema(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    _upgrade_head(url)

    inspector = inspect(create_engine(url))
    tables = set(inspector.get_table_names())
    assert {"deployments", "api_keys", "events", "alembic_version"} <= tables

    dep_cols = {c["name"] for c in inspector.get_columns("deployments")}
    assert dep_cols == {
        "id", "user_id", "scenario", "status",
        "created_at", "updated_at", "outputs", "error", "provider",
        "expires_at",  # added by migration 0002
    }
    event_cols = {c["name"] for c in inspector.get_columns("events")}
    assert event_cols == {"id", "lab_id", "ts", "actor", "type", "payload"}


def test_migrated_schema_matches_models_create_all(tmp_path, monkeypatch):
    """The baseline migration and Base.metadata must describe the same tables."""
    import models

    migrated_url = f"sqlite:///{tmp_path / 'a.db'}"
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    _upgrade_head(migrated_url)

    created_engine = create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    models.Base.metadata.create_all(created_engine)

    migrated, created = inspect(create_engine(migrated_url)), inspect(created_engine)
    for table in ("deployments", "api_keys", "events"):
        migrated_cols = {c["name"]: c["type"].__class__.__name__
                         for c in migrated.get_columns(table)}
        created_cols = {c["name"]: c["type"].__class__.__name__
                        for c in created.get_columns(table)}
        assert migrated_cols == created_cols, table
