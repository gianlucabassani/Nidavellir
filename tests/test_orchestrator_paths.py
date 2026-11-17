"""
Regression tests for ROADMAP audit issue #1 (Docker production path bug).

The provisioning code used to recompute TF_SOURCE_DIR / RUNS_DIR from
__file__, shadowing config.py and ignoring the RUNS_DIR env var — in the
container that resolved to unmounted paths. These tests pin the fix at its
post-ADR-0003 home: the OpenStack provider must consume config.py, and
config.py's Docker branch must match the actual image layout.
"""
import importlib
import os
from pathlib import Path

import config
import providers.openstack as openstack_provider
from orchestrator import Orchestrator
from providers.openstack import OpenStackProvider


def test_provider_consumes_config_paths():
    """The provider's paths must be the config ones (incl. env overrides)."""
    assert openstack_provider.BASE_TERRAFORM_TEMPLATE == config.BASE_TERRAFORM_TEMPLATE
    assert openstack_provider.RUNS_DIR == config.RUNS_DIR
    # conftest.py points RUNS_DIR at a temp dir via the env var; the old code
    # ignored it and wrote to <repo>/runs.
    assert str(openstack_provider.RUNS_DIR) == os.environ["RUNS_DIR"]


def test_prepare_workspace_copies_configured_template(tmp_path, monkeypatch):
    """Workspaces are cloned from BASE_TERRAFORM_TEMPLATE into RUNS_DIR."""
    template = tmp_path / "template"
    template.mkdir()
    (template / "main.tf").write_text('output "ok" { value = "ok" }\n')
    runs = tmp_path / "runs"

    monkeypatch.setattr(openstack_provider, "BASE_TERRAFORM_TEMPLATE", template)
    monkeypatch.setattr(openstack_provider, "RUNS_DIR", runs)

    work_dir = OpenStackProvider()._prepare_workspace("path-test")

    assert work_dir == runs / "path-test"
    assert (work_dir / "main.tf").exists()
    # Per-lab state isolation: the local-backend override must be written.
    assert (work_dir / "backend_override.tf").exists()


def test_load_scenario_resolves_via_templates_dir():
    """Scenario loading must go through config.TEMPLATES_DIR (not __file__ math)."""
    scenario = Orchestrator()._load_scenario("basic_pentest")
    assert scenario is not None
    assert scenario["nodes"], "expected the basic_pentest scenario to define nodes"

    assert Orchestrator()._load_scenario("no-such-scenario") is None


def test_docker_branch_paths_match_image_layout(monkeypatch):
    """In Docker, templates live at /app/templates and TF at /app/terraform
    (Dockerfile copies the service to /app; compose mounts the TF templates)."""
    real_exists = os.path.exists
    monkeypatch.setattr(
        os.path, "exists", lambda p: p == "/.dockerenv" or real_exists(p)
    )
    importlib.reload(config)
    try:
        assert config.IN_DOCKER
        assert config.TEMPLATES_DIR == Path("/app/templates")
        assert config.BASE_TERRAFORM_TEMPLATE == Path("/app/terraform")
    finally:
        monkeypatch.undo()
        importlib.reload(config)
