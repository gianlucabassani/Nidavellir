"""
Mock provider: simulates a deployment with canned outputs.

Extracted from the original Orchestrator MOCK_MODE branch — keeps the demo,
tests and CI working with zero cloud cost. Output keys deliberately match
`infra/terraform/outputs.tf` so the UI renders identically in both modes.
"""
import logging
import time

from providers.base import RangeProvider

logger = logging.getLogger(__name__)

# Seconds of fake provisioning delay (visible status progression in the UI).
MOCK_DEPLOY_DELAY = 2


class MockProvider(RangeProvider):
    name = "mock"

    def deploy(self, scenario_config, instance_id, user_vars=None):
        logger.info(f"[{instance_id}] 🎭 SIMULATING DEPLOY...")
        time.sleep(MOCK_DEPLOY_DELAY)

        fake_outputs = {
            "soc_dashboard_url": "https://192.168.1.50:443",
            "soc_credentials": {"username": "admin", "password": "SecretPassword!"},
            "log_vm_ssh_command": "ssh ubuntu@192.168.1.50",
            "log_vm_private_ip": "192.168.0.5",
            "log_vm_floating_ip": "192.168.1.50",

            "attack_vm_ssh_command": "ssh kali@192.168.1.80",
            "attack_vm_private_ip": "192.168.50.10",
            "attack_vm_floating_ip": "192.168.1.80",

            "victim_vm_private_ip": "192.168.0.10",
            "victim_vm_floating_ip": "192.168.1.60",
        }
        return {"success": True, "outputs": fake_outputs}

    def destroy(self, instance_id):
        logger.info(f"[{instance_id}] 🎭 SIMULATING DESTROY...")
        return {"success": True}
