"""FR-01 (B10, U4): migrations run at deploy; drift is refused, not masked.

Alembic's env.py resolves the URL from DATABASE_URL, so every test sets it.
"""
import os
import subprocess  # nosec B404 - fixed argv
import sys
from pathlib import Path

import pytest

pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

import migrate  # noqa: E402

_ORCH = Path(__file__).resolve().parent.parent / "cyber-range" / "services" / "scenario-orchestrator"


def _cols(url, table):
    return {c["name"] for c in inspect(create_engine(url)).get_columns(table)}


def _at(tmp_path, monkeypatch, revision, name="db.sqlite"):
    url = f"sqlite:///{tmp_path / name}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migrate._alembic_config(url), revision)
    return url


def test_u4_create_all_does_not_add_a_migration_column(tmp_path, monkeypatch):
    """U4 proven: the pre-FR-01 start-up bootstrap (`create_all`) leaves a
    0009 database without the 0010 column — the schema change never arrives."""
    import models

    url = _at(tmp_path, monkeypatch, "0009")
    assert "encrypted_headers" not in _cols(url, "model_connections")
    models.Base.metadata.create_all(create_engine(url))  # what every start did
    assert "encrypted_headers" not in _cols(url, "model_connections")


def test_deploy_path_from_0009_reaches_head(tmp_path, monkeypatch):
    url = _at(tmp_path, monkeypatch, "0009")
    actions = migrate.migrate(url)
    assert "encrypted_headers" in _cols(url, "model_connections")
    assert migrate.current_revision(create_engine(url)) == migrate.head_revision()
    assert actions and actions[0].startswith("upgrade 0009")


def test_migrate_main_is_the_compose_entrypoint(tmp_path, monkeypatch):
    url = _at(tmp_path, monkeypatch, "0009")
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(_ORCH)}
    proc = subprocess.run([sys.executable, "-m", "migrate"], cwd=_ORCH, env=env,  # nosec B603
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "encrypted_headers" in _cols(url, "model_connections")


def test_adopts_an_unversioned_create_all_database(tmp_path, monkeypatch):
    """Production before FR-01: tables from create_all, no alembic_version, and
    columns added by later revisions missing on old tables."""
    url = _at(tmp_path, monkeypatch, "0001")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
    actions = migrate.migrate(url)
    assert "add column deployments.expires_at" in actions
    assert "add column deployments.effective_provider" in actions
    assert any(a.startswith("create table model_connections") for a in actions)
    assert migrate.current_revision(engine) == migrate.head_revision()
    names = {ix["name"] for ix in inspect(engine).get_indexes("events")}
    assert {"ix_events_lab_type_id", "ix_events_type_id"} <= names
    migrate.verify_matches_models(engine)
    assert migrate.migrate(url) == [f"upgrade {migrate.head_revision()} -> {migrate.head_revision()}"]


def test_empty_database_is_built_by_upgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'empty.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate.migrate(url)
    assert migrate.current_revision(create_engine(url)) == migrate.head_revision()


def test_check_schema_head_refuses_mismatch(tmp_path, monkeypatch):
    url = _at(tmp_path, monkeypatch, "0010")
    with pytest.raises(migrate.SchemaDriftError, match="0010.*expects"):
        migrate.check_schema_head(create_engine(url))
    bare = create_engine(f"sqlite:///{tmp_path / 'bare.sqlite'}")
    with pytest.raises(migrate.SchemaDriftError, match="unversioned"):
        migrate.check_schema_head(bare)


@pytest.mark.parametrize("url, env, required", [
    ("postgresql+psycopg://u@h/db", {"MOCK_MODE": "false"}, True),
    ("postgresql+psycopg://u@h/db", {"MOCK_MODE": "true"}, False),
    ("sqlite:///x.db", {"MOCK_MODE": "false"}, False),
    ("sqlite:///x.db", {"NIDAVELLIR_SCHEMA_CHECK": "strict"}, True),
])
def test_guard_applies_to_postgres_outside_mock(url, env, required):
    assert migrate.schema_check_required(url, env) is required


def test_api_exits_non_zero_on_revision_mismatch(tmp_path, monkeypatch):
    url = _at(tmp_path, monkeypatch, "0010")
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(_ORCH),
           "MOCK_MODE": "true", "NIDAVELLIR_SCHEMA_CHECK": "strict",
           "DATA_DIR": str(tmp_path / "data"), "RUNS_DIR": str(tmp_path / "runs"),
           "KEYS_DIR": str(tmp_path / "keys"), "CACHE_DIR": str(tmp_path / "cache")}
    proc = subprocess.run([sys.executable, "-c", "import api"], cwd=_ORCH, env=env,  # nosec B603
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0
    assert "code expects" in proc.stderr and "python -m migrate" in proc.stderr


def test_compose_runs_migrate_before_services():
    import yaml

    root = _ORCH.parent.parent.parent
    base = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]
    assert base["migrate"]["command"] == ["python", "-m", "migrate"]
    for svc in ("orchestrator", "worker", "beat"):
        assert base[svc]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    # deploy.sh starts `orchestrator` with `up --wait`, which pulls `migrate` in as a
    # dependency and fails the deploy when it exits non-zero. `migrate` is kept out
    # of SERVICES so a rollback to a pre-FR-01 compose file still resolves.
    prod = yaml.safe_load((root / "docker-compose.prod.yml").read_text().replace("!override", "")
                          .replace("!reset", ""))["services"]
    assert prod["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
