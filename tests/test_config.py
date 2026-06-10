"""
Tests for configuration validation (config.validate_config).

Covers the mock-mode happy path (no OpenStack creds required) and the
production guard that refuses to start without credentials.
"""
import importlib

import pytest


def test_validate_config_passes_in_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    import config

    # Should not raise, and should create the runtime directories.
    config.validate_config()
    assert config.RUNS_DIR.exists()
    assert config.DATA_DIR.exists()


def test_validate_config_requires_creds_in_prod(monkeypatch):
    """With MOCK_MODE off and no OpenStack creds, startup must fail loudly."""
    monkeypatch.setenv("MOCK_MODE", "false")
    for var in (
        "OS_USERNAME",
        "OS_PASSWORD",
        "OS_PROJECT_ID",
        "OS_TENANT_ID",
        "OS_AUTH_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    import config

    # Re-import so the module-level credential constants reflect the cleared env.
    importlib.reload(config)
    with pytest.raises(ValueError) as exc:
        config.validate_config()
    assert "OS_USERNAME" in str(exc.value)
