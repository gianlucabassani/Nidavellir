"""FR-01 (B10, U4): bring the database schema to the code's Alembic head.

Run as a one-shot before the API, worker and beat start (Compose service
``migrate``: ``python -m migrate``). Exit status is non-zero on any failure, so
dependent services do not start and ``scripts/deploy.sh`` fails and rolls back.

Three cases:

* versioned database (``alembic_version`` present) -> ``alembic upgrade head``;
* empty database -> ``alembic upgrade head`` (builds the full schema);
* **unversioned** database that already has application tables -> *adopt* it.
  Before FR-01 nothing ran Alembic in a deployment: ``create_all`` created missing
  tables at every start but never added columns (U4). Such a database matches no
  single revision, so it cannot be upgraded step by step. Adoption adds missing
  model tables, missing *nullable* columns and missing indexes, verifies that every
  model table and column now exists, then stamps ``head``. A missing NOT NULL
  column, or any other mismatch, is refused for the operator to resolve.

Separately, :func:`check_schema_head` is the start-up guard: on PostgreSQL outside
mock mode a service refuses to start unless the database revision equals head.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger("migrate")

_HERE = Path(__file__).resolve().parent


class SchemaDriftError(RuntimeError):
    """The database schema revision does not match the code's head."""


def _alembic_config(url: str):
    from alembic.config import Config  # noqa: PLC0415

    cfg = Config(str(_HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(_HERE / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head_revision() -> str:
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    return ScriptDirectory.from_config(_alembic_config("sqlite://")).get_current_head()


def current_revision(engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    return rows[0][0] if len(rows) == 1 else ",".join(sorted(r[0] for r in rows)) or None


def _model_tables() -> set[str]:
    from models import Base  # noqa: PLC0415

    return set(Base.metadata.tables)


def adopt_unversioned(engine) -> list[str]:
    """Repair a create_all-built database to the model schema and stamp head."""
    from models import Base  # noqa: PLC0415

    actions: list[str] = []
    live = inspect(engine)
    existing = set(live.get_table_names())
    missing_tables = [t for t in Base.metadata.sorted_tables if t.name not in existing]
    for table in missing_tables:
        table.create(engine)
        actions.append(f"create table {table.name}")
    problems: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            cols = {c["name"] for c in live.get_columns(table.name)}
            for column in table.columns:
                if column.name in cols:
                    continue
                if not column.nullable or column.primary_key:
                    problems.append(f"{table.name}.{column.name} is NOT NULL")
                    continue
                coltype = column.type.compile(dialect=engine.dialect)
                prep = engine.dialect.identifier_preparer
                conn.execute(text(
                    f"ALTER TABLE {prep.quote(table.name)} "
                    f"ADD COLUMN {prep.quote(column.name)} {coltype}"))
                actions.append(f"add column {table.name}.{column.name}")
    if problems:
        raise SchemaDriftError("cannot adopt unversioned database: " + "; ".join(problems))
    live = inspect(engine)
    for table in Base.metadata.sorted_tables:
        have = {ix["name"] for ix in live.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have:
                index.create(engine)
                actions.append(f"create index {index.name}")
    verify_matches_models(engine)
    from alembic import command  # noqa: PLC0415

    command.stamp(_alembic_config(str(engine.url)), "head")
    actions.append(f"stamp {head_revision()}")
    return actions


def verify_matches_models(engine) -> None:
    from models import Base  # noqa: PLC0415

    live = inspect(engine)
    tables = set(live.get_table_names())
    missing = []
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            missing.append(table.name)
            continue
        cols = {c["name"] for c in live.get_columns(table.name)}
        missing += [f"{table.name}.{c.name}" for c in table.columns if c.name not in cols]
    if missing:
        raise SchemaDriftError("schema still differs from models: " + ", ".join(missing))


def migrate(url: str) -> list[str]:
    """Bring ``url`` to head. Returns a list of human-readable actions."""
    from alembic import command  # noqa: PLC0415

    engine = create_engine(url)
    try:
        revision = current_revision(engine)
        app_tables = _model_tables() & set(inspect(engine).get_table_names())
        if revision is None and app_tables:
            logger.warning("unversioned database with %d application tables: adopting",
                           len(app_tables))
            return adopt_unversioned(engine)
        command.upgrade(_alembic_config(url), "head")
        return [f"upgrade {revision or 'empty'} -> {head_revision()}"]
    finally:
        engine.dispose()


def schema_check_required(url: str, env=None) -> bool:
    """The start-up guard applies on PostgreSQL outside mock mode.

    SQLite (dev, tests, the mock demo) keeps the idempotent ``create_all``
    bootstrap. ``NIDAVELLIR_SCHEMA_CHECK=strict`` forces the guard anywhere.
    """
    env = os.environ if env is None else env
    if env.get("NIDAVELLIR_SCHEMA_CHECK", "").lower() == "strict":
        return True
    if env.get("MOCK_MODE", "false").lower() == "true":
        return False
    return not url.startswith("sqlite")


def check_schema_head(engine) -> None:
    """Raise :class:`SchemaDriftError` unless the database is at head."""
    head = head_revision()
    current = current_revision(engine)
    if current != head:
        raise SchemaDriftError(
            f"database schema revision is {current or 'unversioned'}, code expects {head}. "
            "Run the migration step (`python -m migrate`, the `migrate` Compose service) "
            "before starting the API, worker or beat.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from database import database_url  # noqa: PLC0415

    url = database_url()
    try:
        for action in migrate(url):
            logger.info("migrate: %s", action)
        engine = create_engine(url)
        try:
            check_schema_head(engine)
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 - any failure must stop the deploy
        logger.error("migration failed: %s", exc)
        return 1
    logger.info("schema at head %s", head_revision())
    return 0


if __name__ == "__main__":
    sys.exit(main())
