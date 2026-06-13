"""
OpenStack provider: per-instance OpenTofu workspaces against an OpenStack
cloud. Extracted verbatim from the original Orchestrator real-mode logic
(ADR-0003) — the workspace-per-lab + local-backend-override pattern from
ADR-0001 lives here now.
"""
import json
import logging
import shutil
import subprocess
from pathlib import Path

from config import BASE_TERRAFORM_TEMPLATE, RUNS_DIR
from providers.base import RangeProvider
from redaction import redact, redact_mapping

logger = logging.getLogger(__name__)


class OpenStackProvider(RangeProvider):
    name = "openstack"
    infra_class = "vm"

    def __init__(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

    def _prepare_workspace(self, instance_id: str) -> Path:
        work_dir = RUNS_DIR / instance_id
        if work_dir.exists():
            shutil.rmtree(work_dir)
        shutil.copytree(BASE_TERRAFORM_TEMPLATE, work_dir)

        # Backend override ensures each lab has its own terraform.tfstate file
        backend_override = work_dir / "backend_override.tf"
        backend_override.write_text('''
    terraform {
    backend "local" {
        path = "terraform.tfstate"
    }
    }
    ''')

        logger.info(f"[{instance_id}] Workspace prepared at {work_dir}")
        return work_dir

    def deploy(self, scenario_config, instance_id, user_vars=None):
        work_dir = None
        try:
            work_dir = self._prepare_workspace(instance_id)

            # STEP 1: TERRAFORM INIT (with retry)
            logger.info(f"[{instance_id}] Running terraform init...")
            for attempt in range(3):
                try:
                    subprocess.run(
                        ["tofu", "init"],
                        cwd=work_dir,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 min timeout
                    )
                    logger.info(f"[{instance_id}] Init successful")
                    break

                except subprocess.TimeoutExpired:
                    if attempt == 2:
                        raise RuntimeError("Terraform init timed out after 3 attempts")
                    logger.warning(f"[{instance_id}] Init timeout, retry {attempt+1}/3")
                except subprocess.CalledProcessError as e:
                    if attempt == 2:
                        # stderr may echo OpenStack creds passed via the env.
                        raise RuntimeError(f"Init failed: {redact(e.stderr)}")

            # STEP 2: TERRAFORM APPLY
            logger.info(f"[{instance_id}] Applying scenario")
            cmd = ["tofu", "apply", "-auto-approve", "-json"]

            # Inject scenario specific vars
            scenario_vars = self._extract_terraform_vars(scenario_config)
            for key, value in scenario_vars.items():
                cmd.extend(["-var", f"{key}={value}"])

            # Merge with user variable overrides
            if user_vars:
                for key, value in user_vars.items():
                    cmd.extend(["-var", f"{key}={value}"])

            # instance-specific naming...
            cmd.extend(["-var", f"vm_name=att-{instance_id[:8]}"])

            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=1800  # 30 min max
            )

            if result.returncode != 0:
                # Redact first (stderr can echo OpenStack creds), then keep the
                # last 2000 chars for debugging.
                error_msg = redact(result.stderr)[-2000:] if result.stderr else "Unknown error"
                logger.error(f"[{instance_id}] Apply failed: {error_msg}")

                # CLEANUP FAILED WORKSPACE
                if work_dir.exists():
                    shutil.rmtree(work_dir)

                return {
                    "success": False,
                    "error": f"Terraform apply failed: {error_msg}"
                }

            logger.info(f"[{instance_id}] Deployment successful")
            return {
                "success": True,
                "outputs": self._get_outputs(work_dir)
            }

        except subprocess.TimeoutExpired:
            logger.error(f"[{instance_id}] Deployment timed out")
            if work_dir and work_dir.exists():
                shutil.rmtree(work_dir)
            return {
                "success": False,
                "error": "Deployment timed out (exceeded 30 minutes)"
            }

        except Exception as e:
            logger.error(f"[{instance_id}] Unexpected error: {str(e)}")
            if work_dir and work_dir.exists():
                shutil.rmtree(work_dir)
            return {
                "success": False,
                "error": str(e)
            }

    def destroy(self, instance_id):
        work_dir = RUNS_DIR / instance_id

        if not work_dir.exists():
            logger.warning(f"[{instance_id}] Workspace not found, nothing to destroy")
            return {"success": True}

        try:
            logger.info(f"[{instance_id}] Running terraform destroy...")
            result = subprocess.run(
                ["tofu", "destroy", "-auto-approve"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=900  # 15 min
            )

            if result.returncode != 0:
                safe_stderr = redact(result.stderr) if result.stderr else "Unknown error"
                logger.error(f"[{instance_id}] Destroy failed: {safe_stderr}")
                return {
                    "success": False,
                    "error": f"Terraform destroy failed: {safe_stderr[-1000:]}"
                }

            # CLEANUP WORKSPACE
            shutil.rmtree(work_dir)
            logger.info(f"[{instance_id}] Workspace cleaned up")

            return {"success": True}

        except Exception as e:
            logger.error(f"[{instance_id}] Destroy error: {str(e)}")
            return {"success": False, "error": str(e)}

    def _get_outputs(self, work_dir: Path):
        """Read terraform outputs, flattened to {name: value}.

        `tofu output -json` wraps every output in {"value": ..., "type": ...};
        we unwrap here so DB/UI/consumers see one shape — the same one the
        mock outputs use.
        """
        try:
            res = subprocess.run(
                ["tofu", "output", "-json"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            raw = json.loads(res.stdout)
            return {
                key: (entry.get("value") if isinstance(entry, dict) and "value" in entry else entry)
                for key, entry in raw.items()
            }
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read terraform outputs in {work_dir}: {e}")
            return {}

    def _extract_terraform_vars(self, scenario_config: dict) -> dict:
        """
        Extract Terraform variables from scenario YAML

        Maps scenario.yaml values to terraform variables:
        - vms[0].image → victim_image_name
        - vms[1].image → image_name (attacker)
        - vms[2].image → log_image_name (monitor)
        """
        vars = {}

        # Map VM definitions to Terraform variables
        for vm in scenario_config.get('vms', []):
            role = vm.get('role')

            if role == 'victim':
                vars['victim_image_name'] = vm.get('image', 'victim-web')
                vars['victim_vm_name'] = vm.get('name', 'cyber_guard_victim')
                if 'flavor' in vm:
                    vars['flavor_name'] = vm['flavor']

            elif role == 'attacker':
                vars['image_name'] = vm.get('image', 'kali-linux-2025-cloud')
                vars['vm_name'] = vm.get('name', 'cyber_guard_attack')

            elif role == 'monitor':
                vars['log_image_name'] = vm.get('image', 'ubuntu_cloud')
                vars['log_vm_name'] = vm.get('name', 'cyber_guard_log')
                if 'flavor' in vm:
                    vars['soc_flavor_name'] = vm['flavor']

        # Network configuration
        if 'network' in scenario_config:
            net = scenario_config['network']
            if 'cidr' in net:
                vars['private_cidr'] = net['cidr']

        logger.info(f"Extracted Terraform vars: {redact_mapping(vars)}")
        return vars
