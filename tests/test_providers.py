"""
Tests for the RangeProvider driver layer (ADR-0003).

Pins: provider selection precedence (arg > RANGE_PROVIDER > MOCK_MODE >
openstack default), the mock provider's contract, and that the Orchestrator
is a pure dispatcher (loads the scenario, delegates, never reaches a
provider with an invalid scenario).
"""
import pytest

import providers
from orchestrator import Orchestrator
from providers.mock import MockProvider
from providers.openstack import OpenStackProvider


class _RecordingProvider:
    name = "recording"

    def __init__(self):
        self.deploys = []
        self.destroys = []

    def deploy(self, scenario_config, instance_id, user_vars=None):
        self.deploys.append((scenario_config, instance_id, user_vars))
        return {"success": True, "outputs": {}}

    def destroy(self, instance_id):
        self.destroys.append(instance_id)
        return {"success": True}


# --- selection ---------------------------------------------------------------


def test_explicit_name_wins(monkeypatch):
    monkeypatch.setenv("RANGE_PROVIDER", "openstack")
    assert isinstance(providers.get_provider("mock"), MockProvider)


def test_env_var_overrides_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("RANGE_PROVIDER", "openstack")
    assert isinstance(providers.get_provider(), OpenStackProvider)


def test_mock_mode_falls_back_to_mock(monkeypatch):
    monkeypatch.delenv("RANGE_PROVIDER", raising=False)
    monkeypatch.setenv("MOCK_MODE", "true")
    assert isinstance(providers.get_provider(), MockProvider)


def test_default_is_openstack(monkeypatch):
    monkeypatch.delenv("RANGE_PROVIDER", raising=False)
    monkeypatch.setenv("MOCK_MODE", "false")
    assert isinstance(providers.get_provider(), OpenStackProvider)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        providers.get_provider("does-not-exist")


# --- mock provider contract --------------------------------------------------


def test_mock_deploy_returns_ui_compatible_outputs(monkeypatch):
    import providers.mock as mock_module

    monkeypatch.setattr(mock_module.time, "sleep", lambda s: None)
    result = MockProvider().deploy({}, "test-id")

    assert result["success"] is True
    # Keys the dashboard renders — must match infra/terraform/outputs.tf names.
    for key in (
        "attack_vm_floating_ip",
        "victim_vm_floating_ip",
        "log_vm_floating_ip",
        "soc_dashboard_url",
        "soc_credentials",
    ):
        assert key in result["outputs"], key


def test_mock_destroy_is_idempotent():
    assert MockProvider().destroy("never-existed") == {"success": True}


# --- orchestrator dispatch ---------------------------------------------------


def test_orchestrator_delegates_with_loaded_config():
    recorder = _RecordingProvider()
    result = Orchestrator(provider=recorder).deploy("basic_pentest", "dispatch-1")

    assert result["success"] is True
    (config, instance_id, _), = recorder.deploys
    assert instance_id == "dispatch-1"
    assert config["vms"], "provider must receive the parsed scenario config"


def test_orchestrator_blocks_unknown_scenario_before_provider():
    recorder = _RecordingProvider()
    result = Orchestrator(provider=recorder).deploy("no-such-scenario", "dispatch-2")

    assert result["success"] is False
    assert "not found" in result["error"]
    assert recorder.deploys == []


def test_orchestrator_destroy_delegates():
    recorder = _RecordingProvider()
    assert Orchestrator(provider=recorder).destroy("x")["success"] is True
    assert recorder.destroys == ["x"]


def test_orchestrator_default_provider_respects_mock_mode():
    # conftest sets MOCK_MODE=true for the whole suite.
    assert isinstance(Orchestrator().provider, MockProvider)
