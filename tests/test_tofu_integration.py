"""
Integration test for the provisioning path (ROADMAP Phase 1, audit #1).

Runs a real `tofu init` inside a workspace prepared by the Orchestrator,
against a throwaway provider-free template — proving the workspace layout
(template copy + local-backend override) is something OpenTofu actually
accepts, without touching any cloud. Skipped when tofu/terraform is not
installed (CI installs OpenTofu).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import orchestrator

TOFU = shutil.which("tofu") or shutil.which("terraform")


@pytest.mark.integration
@pytest.mark.skipif(TOFU is None, reason="tofu/terraform binary not installed")
def test_tofu_init_succeeds_in_prepared_workspace(tmp_path, monkeypatch):
    template = tmp_path / "template"
    template.mkdir()
    (template / "main.tf").write_text('output "ok" { value = "ok" }\n')

    monkeypatch.setattr(orchestrator, "BASE_TERRAFORM_TEMPLATE", template)
    monkeypatch.setattr(orchestrator, "RUNS_DIR", tmp_path / "runs")
    # conftest points the plugin cache at a temp path; tofu errors if the
    # configured cache dir does not exist.
    Path(os.environ["TF_PLUGIN_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)

    work_dir = orchestrator.Orchestrator()._prepare_workspace("tofu-itest")

    result = subprocess.run(
        [TOFU, "init", "-no-color", "-input=false"],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"
    assert "successfully initialized" in result.stdout
