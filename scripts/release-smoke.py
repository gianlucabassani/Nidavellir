#!/usr/bin/env python3
"""Fail-fast release smoke checks for migrations and public service surfaces."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import platform
import sys
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = ROOT / "cyber-range" / "services" / "scenario-orchestrator"
GATEWAY = ROOT / "cyber-range" / "services" / "agent-gateway"
WEBUI = ROOT / "cyber-range" / "webui"


def _prepare_environment(state: Path) -> str:
    database_url = f"sqlite:///{state / 'smoke.db'}"
    values = {
        "MOCK_MODE": "true",
        "DATABASE_URL": database_url,
        "DATABASE_PATH": str(state / "smoke.db"),
        "RUNS_DIR": str(state / "runs"),
        "DATA_DIR": str(state / "data"),
        "KEYS_DIR": str(state / "keys"),
        "CACHE_DIR": str(state / "cache"),
        "TF_PLUGIN_CACHE_DIR": str(state / "cache" / "terraform-plugins"),
        "RATE_LIMIT_ENABLED": "false",
        "SECRETS_ENCRYPTION_KEY": "",
        "ORCHESTRATOR_URL": "http://127.0.0.1:9",
        "NIDAVELLIR_STANCE": "attacker",
    }
    os.environ.update(values)
    sys.path.insert(0, str(GATEWAY))
    sys.path.insert(0, str(ORCHESTRATOR))
    return database_url


def _migration_smoke(database_url: str) -> None:
    cfg = Config(str(ORCHESTRATOR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ORCHESTRATOR / "migrations"))
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(database_url)).get_table_names())
    required = {"alembic_version", "api_keys", "deployments", "events"}
    assert required <= tables, f"migration missing tables: {sorted(required - tables)}"


def _api_smoke() -> None:
    from fastapi.testclient import TestClient

    import api

    response = TestClient(api.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _webui_smoke() -> None:
    spec = importlib.util.spec_from_file_location("nidavellir_webui_smoke", WEBUI / "app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config["TESTING"] = True
    module.app.template_folder = str(WEBUI / "templates")
    response = module.app.test_client().get("/login")
    assert response.status_code == 200
    assert b"csrf_token" in response.data


def _gateway_smoke() -> None:
    from gateway.config import GatewayConfig
    from gateway.server import build_server

    cfg = GatewayConfig(
        env={
            "NIDAVELLIR_GATEWAY_HOST": "127.0.0.1",
            "NIDAVELLIR_STANCE": "attacker",
        }
    )
    tools = {tool.name for tool in asyncio.run(build_server(cfg).list_tools())}
    required = {"arena_status", "get_briefing", "http_request", "run_command"}
    assert required <= tools, f"gateway missing tools: {sorted(required - tools)}"


def main() -> None:
    assert sys.version_info[:2] == (3, 11), "release smoke requires Python 3.11"
    print(f"release smoke: Python {platform.python_version()}")
    with tempfile.TemporaryDirectory(prefix="nidavellir-release-smoke-") as raw_state:
        database_url = _prepare_environment(Path(raw_state))
        _migration_smoke(database_url)
        _api_smoke()
        _webui_smoke()
        _gateway_smoke()
    print("release smoke: migrations, API, UI and gateway ready")


if __name__ == "__main__":
    main()
