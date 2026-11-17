"""
TerraformDriver — shared OpenTofu plumbing for cloud providers (ADR-0003).

Factors out the per-arena workspace pattern (copy a template dir into
``runs/<arena>/``, write a local-backend override so each arena has its own
state file, ``init`` → ``apply`` → ``output``, idempotent ``destroy``) so a new
cloud backend only has to supply its template, its variables, and any output
post-processing.

Subclass contract:
- ``_template_dir()`` / ``_runs_dir()`` — the module to copy and where to run it
  (methods, resolved at call time, so paths stay monkeypatchable in tests).
- ``_write_vars(work_dir, scenario_config, instance_id, user_vars)`` — write any
  ``*.tfvars.json`` into the workspace and/or return extra ``-var k=v`` args.
- ``_post_process_outputs(outputs)`` — optional; reshape the flattened tofu
  outputs (e.g. fan a per-node map out into ``node_<name>_*`` keys).

The legacy ``openstack`` driver predates this base and still carries its own
copy of the plumbing; it should migrate onto this once its generic ``nodes[]``
module lands (future work — needs OpenStack creds to verify).
"""
import json
import logging
import shutil
import subprocess
from pathlib import Path

from providers.base import RangeProvider
from redaction import redact

logger = logging.getLogger(__name__)

INIT_TIMEOUT = 300
APPLY_TIMEOUT = 1800
DESTROY_TIMEOUT = 900
OUTPUT_TIMEOUT = 60

_BACKEND_OVERRIDE = """terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
"""


class TerraformDriver(RangeProvider):
    """Base for providers that deploy a per-arena OpenTofu workspace."""

    def _template_dir(self) -> Path:  # pragma: no cover - abstract
        raise NotImplementedError

    def _runs_dir(self) -> Path:  # pragma: no cover - abstract
        raise NotImplementedError

    # --- subclass hooks -------------------------------------------------------

    def _write_vars(self, work_dir, scenario_config, instance_id, user_vars) -> list[str]:
        """Write var files into ``work_dir`` and/or return extra CLI ``-var``
        args. Default: no variables."""
        return []

    def _post_process_outputs(self, outputs: dict) -> dict:
        return outputs

    # --- workspace ------------------------------------------------------------

    def _prepare_workspace(self, instance_id: str) -> Path:
        runs = self._runs_dir()
        runs.mkdir(parents=True, exist_ok=True)
        work_dir = runs / instance_id
        if work_dir.exists():
            shutil.rmtree(work_dir)
        shutil.copytree(self._template_dir(), work_dir)
        (work_dir / "backend_override.tf").write_text(_BACKEND_OVERRIDE)
        logger.info(f"[{instance_id}] Workspace prepared at {work_dir}")
        return work_dir

    # --- lifecycle ------------------------------------------------------------

    def deploy(self, scenario_config, instance_id, user_vars=None):
        work_dir = None
        try:
            work_dir = self._prepare_workspace(instance_id)
            self._init(work_dir, instance_id)
            extra_args = self._write_vars(work_dir, scenario_config, instance_id, user_vars)
            self._apply(work_dir, instance_id, extra_args)
            outputs = self._post_process_outputs(self._read_outputs(work_dir))
            logger.info(f"[{instance_id}] {self.name} deployment successful")
            return {"success": True, "outputs": outputs}
        except subprocess.TimeoutExpired:
            logger.error(f"[{instance_id}] Deployment timed out")
            self._cleanup(work_dir)
            return {"success": False, "error": "Deployment timed out"}
        except Exception as e:
            logger.error(f"[{instance_id}] {self.name} deploy failed: {e}")
            self._cleanup(work_dir)
            return {"success": False, "error": str(e)}

    def destroy(self, instance_id):
        work_dir = self._runs_dir() / instance_id
        if not work_dir.exists():
            logger.warning(f"[{instance_id}] Workspace not found, nothing to destroy")
            return {"success": True}
        try:
            result = subprocess.run(
                ["tofu", "destroy", "-auto-approve", "-no-color", "-input=false"],
                cwd=work_dir, capture_output=True, text=True, timeout=DESTROY_TIMEOUT,
            )
            if result.returncode != 0:
                safe = redact(result.stderr)[-1000:] if result.stderr else "Unknown error"
                logger.error(f"[{instance_id}] Destroy failed: {safe}")
                return {"success": False, "error": f"Terraform destroy failed: {safe}"}
            shutil.rmtree(work_dir)
            logger.info(f"[{instance_id}] Workspace cleaned up")
            return {"success": True}
        except Exception as e:
            logger.error(f"[{instance_id}] Destroy error: {e}")
            return {"success": False, "error": str(e)}

    # --- tofu steps -----------------------------------------------------------

    def _init(self, work_dir, instance_id):
        for attempt in range(3):
            try:
                subprocess.run(
                    ["tofu", "init", "-no-color", "-input=false"],
                    cwd=work_dir, check=True, capture_output=True, text=True,
                    timeout=INIT_TIMEOUT,
                )
                logger.info(f"[{instance_id}] tofu init successful")
                return
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise RuntimeError("tofu init timed out after 3 attempts")
                logger.warning(f"[{instance_id}] init timeout, retry {attempt + 1}/3")
            except subprocess.CalledProcessError as e:
                if attempt == 2:
                    raise RuntimeError(f"tofu init failed: {redact(e.stderr)}") from None

    def _apply(self, work_dir, instance_id, extra_args):
        cmd = ["tofu", "apply", "-auto-approve", "-no-color", "-input=false", *extra_args]
        result = subprocess.run(
            cmd, cwd=work_dir, capture_output=True, text=True, timeout=APPLY_TIMEOUT
        )
        if result.returncode != 0:
            # stderr can echo cloud credentials → redact before logging/returning.
            error = redact(result.stderr)[-2000:] if result.stderr else "Unknown error"
            raise RuntimeError(f"Terraform apply failed: {error}")
        logger.info(f"[{instance_id}] apply complete")

    def _read_outputs(self, work_dir) -> dict:
        """Read tofu outputs, unwrapping the ``{"value":…,"type":…}`` envelope
        to the flat ``{name: value}`` shape the rest of the system expects."""
        try:
            res = subprocess.run(
                ["tofu", "output", "-json"],
                cwd=work_dir, check=True, capture_output=True, text=True,
                timeout=OUTPUT_TIMEOUT,
            )
            raw = json.loads(res.stdout)
            return {
                key: (entry.get("value") if isinstance(entry, dict) and "value" in entry else entry)
                for key, entry in raw.items()
            }
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read tofu outputs in {work_dir}: {e}")
            return {}

    @staticmethod
    def _cleanup(work_dir):
        if work_dir and Path(work_dir).exists():
            shutil.rmtree(work_dir, ignore_errors=True)
