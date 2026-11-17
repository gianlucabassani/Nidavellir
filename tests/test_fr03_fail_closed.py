"""FR-03 (B14, B15, B23): fail closed on insecure configuration outside MOCK_MODE.

One parametrized case per refused condition, for the orchestrator, the console
and the agent gateway; plus the provider default and the Compose contract
(`make dev` still starts with no .env: the dev overlay pins MOCK_MODE).
"""
from pathlib import Path

import pytest
import yaml

import config

pytest.importorskip("flask_wtf")
_ROOT = Path(__file__).resolve().parent.parent

# Import the console through tests.test_webui so its test env is set first
# (the console module reads env at import and is cached for the session).
import tests.test_webui  # noqa: E402,F401
from app import insecure_console_config_errors  # noqa: E402
from gateway.config import GatewayConfig  # noqa: E402
from gateway.server import insecure_gateway_config_errors  # noqa: E402

_GOOD_ORCH = {"MOCK_MODE": "false", "BOOTSTRAP_API_KEY": "cg_real",
              "SECRETS_ENCRYPTION_KEY": "k" * 44}


@pytest.mark.parametrize("override, needle", [
    ({"BOOTSTRAP_API_KEY": "dev-insecure-key"}, "BOOTSTRAP_API_KEY"),
    ({"SECRETS_ENCRYPTION_KEY": ""}, "SECRETS_ENCRYPTION_KEY"),
])
def test_orchestrator_refuses(override, needle):
    errors = config.insecure_config_errors({**_GOOD_ORCH, **override})
    assert any(needle in e for e in errors)


def test_orchestrator_accepts_good_and_mock():
    assert config.insecure_config_errors(_GOOD_ORCH) == []
    assert config.insecure_config_errors({"MOCK_MODE": "true"}) == []


def test_validate_config_exits_on_insecure(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("RANGE_PROVIDER", "docker-local")
    monkeypatch.setenv("BOOTSTRAP_API_KEY", "dev-insecure-key")
    with pytest.raises(ValueError, match="BOOTSTRAP_API_KEY"):
        config.validate_config()


_GOOD_UI = {"MOCK_MODE": "false", "SECRET_KEY": "s3cret", "WEBUI_PASSWORD": "pw",
            "ORCHESTRATOR_API_KEY": "cg_real"}


@pytest.mark.parametrize("override, needle", [
    ({"SECRET_KEY": "change-me"}, "SECRET_KEY"),
    ({"SECRET_KEY": "dev-insecure-change-me"}, "SECRET_KEY"),
    ({"WEBUI_PASSWORD": "nidavellir"}, "WEBUI_PASSWORD"),
    ({"ORCHESTRATOR_API_KEY": "dev-insecure-key"}, "ORCHESTRATOR_API_KEY"),
])
def test_console_refuses(override, needle):
    assert any(needle in e for e in insecure_console_config_errors({**_GOOD_UI, **override}))


def test_console_accepts_good_and_mock():
    assert insecure_console_config_errors(_GOOD_UI) == []
    assert insecure_console_config_errors({"MOCK_MODE": "true"}) == []


@pytest.mark.parametrize("key, status, needle", [
    ("", None, "empty"),
    ("dev-insecure-key", None, "dev key"),
    ("cg_operator", 200, "operator/admin"),
])
def test_gateway_refuses(key, status, needle):
    cfg = GatewayConfig({"NIDAVELLIR_AGENT_KEY": key})
    errors = insecure_gateway_config_errors(cfg, env={"MOCK_MODE": "false"},
                                            probe=lambda _c: status)
    assert any(needle in e for e in errors)


def test_gateway_accepts_agent_key_and_mock():
    cfg = GatewayConfig({"NIDAVELLIR_AGENT_KEY": "cg_agent"})
    assert insecure_gateway_config_errors(cfg, env={"MOCK_MODE": "false"},
                                          probe=lambda _c: 403) == []
    assert insecure_gateway_config_errors(GatewayConfig({}), env={"MOCK_MODE": "true"}) == []


def test_provider_default_is_docker_local(monkeypatch):
    import providers

    monkeypatch.delenv("RANGE_PROVIDER", raising=False)
    monkeypatch.setenv("MOCK_MODE", "false")
    assert providers.resolve_provider_name() == "docker-local"


def _compose(name):
    return yaml.safe_load((_ROOT / name).read_text())


def test_redis_not_published_and_password_required():
    base = _compose("docker-compose.yml")["services"]
    assert "ports" not in base["redis"]
    assert "--requirepass" in base["redis"]["command"]
    for svc in ("orchestrator", "worker", "beat"):
        assert "@redis:6379" in base[svc]["environment"]["CELERY_BROKER_URL"]
    prod = (_ROOT / "docker-compose.prod.yml").read_text()
    assert "REDIS_PASSWORD:?" in prod


def test_make_dev_needs_no_env():
    """The dev overlay pins MOCK_MODE for every service that FR-03 guards."""
    dev = _compose("docker-compose.dev.yml")["services"]
    for svc in ("orchestrator", "webui", "agent-gateway"):
        assert dev[svc]["environment"]["MOCK_MODE"] == "true"
