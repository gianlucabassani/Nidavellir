"""
OpenStack provider: per-arena OpenTofu workspaces against an OpenStack cloud
(ADR-0003). Built on the shared ``TerraformDriver`` — the workspace-per-arena +
local-backend-override plumbing (``init`` → ``apply`` → ``output`` → idempotent
``destroy``, with redaction and soft output parsing) lives in the base now; this
driver only supplies the template/runs dirs, the variable mapping for the (still
fixed 3-VM) template, and the vm/any compatibility check.

The template generalises to a ``nodes[]`` module in Phase 1 (P1-2); the variable
mapping below (canonical victim/attacker/monitor → fixed template vars) is the
seam that change replaces. A real ``apply`` needs OpenStack credentials, so it is
exercised only when they are present (mirrors the AWS driver's posture).
"""
import logging
from pathlib import Path

from config import BASE_TERRAFORM_TEMPLATE, RUNS_DIR
from providers.terraform_base import TerraformDriver
from redaction import redact_mapping
from scenario_spec import normalized_nodes, primary_cidr

logger = logging.getLogger(__name__)


class OpenStackProvider(TerraformDriver):
    name = "openstack"
    infra_class = "vm"

    def _template_dir(self) -> Path:
        return BASE_TERRAFORM_TEMPLATE

    def _runs_dir(self) -> Path:
        return RUNS_DIR

    @staticmethod
    def _supports(scenario_config: dict) -> bool:
        """OpenStack deploys VM-class (and provider-agnostic) scenarios only —
        a container/custom scenario fails fast here instead of dying async in
        the OpenTofu step."""
        required = (scenario_config.get("requires") or {}).get("provider_class", "any")
        return required in ("vm", "any")

    def deploy(self, scenario_config, instance_id, user_vars=None):
        if not self._supports(scenario_config):
            return {
                "success": False,
                "error": (
                    "Scenario requires container-class infrastructure; the "
                    "openstack provider only deploys VM-class scenarios "
                    "(requires.provider_class: vm)"
                ),
            }
        return super().deploy(scenario_config, instance_id, user_vars)

    def _write_vars(self, work_dir, scenario_config, instance_id, user_vars):
        """Map the scenario onto the template's variables as ``-var k=v`` CLI
        args. Order matters: the instance-specific ``vm_name`` is appended last
        so it wins over any value the role mapping produced (matches the
        pre-refactor behaviour)."""
        args: list[str] = []
        for key, value in self._extract_terraform_vars(scenario_config).items():
            args += ["-var", f"{key}={value}"]
        if user_vars:
            for key, value in user_vars.items():
                args += ["-var", f"{key}={value}"]
        args += ["-var", f"vm_name=att-{instance_id[:8]}"]
        return args

    def _extract_terraform_vars(self, scenario_config: dict) -> dict:
        """
        Extract Terraform variables from a scenario, mapping the canonical
        victim/attacker/monitor roles onto the (still fixed 3-VM) template's
        variables. Reads both v3 ``nodes[]`` and legacy ``vms[]`` shapes via
        ``normalized_nodes`` — Phase 1's P1-2 replaces this fixed template with
        a generic ``nodes[]`` module.
        """
        vars = {}

        for vm in normalized_nodes(scenario_config):
            role = vm.get('role')

            if role == 'victim':
                vars['victim_image_name'] = vm.get('image', 'victim-web')
                vars['victim_vm_name'] = vm.get('name', 'nidavellir_victim')
                if vm.get('flavor'):
                    vars['flavor_name'] = vm['flavor']

            elif role == 'attacker':
                vars['image_name'] = vm.get('image', 'kali-linux-2025-cloud')
                vars['vm_name'] = vm.get('name', 'nidavellir_attack')

            elif role == 'monitor':
                vars['log_image_name'] = vm.get('image', 'ubuntu_cloud')
                vars['log_vm_name'] = vm.get('name', 'nidavellir_log')
                if vm.get('flavor'):
                    vars['soc_flavor_name'] = vm['flavor']

        cidr = primary_cidr(scenario_config)
        if cidr:
            vars['private_cidr'] = cidr

        logger.info(f"Extracted Terraform vars: {redact_mapping(vars)}")
        return vars
