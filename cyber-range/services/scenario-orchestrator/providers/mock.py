"""
Mock provider: simulates a deployment with canned outputs.

Extracted from the original Orchestrator MOCK_MODE branch — keeps the demo,
tests and CI working with zero cloud cost. Output keys deliberately match
`infra/terraform/outputs.tf` so the UI renders identically in both modes.
"""
import logging
import time

from providers.base import RangeProvider
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

# Seconds of fake provisioning delay (visible status progression in the UI).
MOCK_DEPLOY_DELAY = 2


class MockProvider(RangeProvider):
    name = "mock"
    infra_class = "any"  # simulates whatever the scenario asks for

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

        # Modern flat `node_<name>_*` contract — what the WebUI _parse_nodes()
        # reads to render the Arena Detail nodes table + topology. Derived from
        # the scenario's own nodes so mock mode mirrors the requested scenario
        # (not a fixed trio); without these keys the nodes table renders empty
        # under MOCK_MODE.
        for i, node in enumerate(normalized_nodes(scenario_config)):
            name = node.get("name")
            if not name:
                continue
            ip = f"192.168.50.{10 + i}"
            is_foothold = node.get("role") == "attacker" or bool(node.get("entrypoint"))
            fake_outputs[f"node_{name}_name"] = name
            fake_outputs[f"node_{name}_private_ip"] = ip
            fake_outputs[f"node_{name}_state"] = "running"
            # Foothold-only shell command — mirrors docker-local so the victim-scope
            # derivation (footholds excluded) behaves the same in mock and for real.
            if is_foothold:
                fake_outputs[f"node_{name}_ssh_command"] = f"ssh user@{ip}  # simulated"
            # SUT victim: surface the clone path + a (simulated) connect command.
            if node.get("sut_clone"):
                clone = node["sut_clone"]
                fake_outputs[f"node_{name}_sut_source"] = clone.get("path") or f"/opt/{name}"
                fake_outputs[f"node_{name}_setup_shell"] = f"docker exec -it nv-mock-{name} /bin/bash  # simulated"
            if node.get("ports"):
                fake_outputs[f"node_{name}_url"] = f"http://{ip}"

        return {"success": True, "outputs": fake_outputs}

    def destroy(self, instance_id):
        logger.info(f"[{instance_id}] 🎭 SIMULATING DESTROY...")
        return {"success": True}

    def exec_in_node(self, instance_id, node, command, timeout=30):
        logger.info(f"[{instance_id}] 🎭 SIMULATING exec on {node}: {command!r}")
        return {
            "success": True,
            "exit_code": 0,
            "stdout": f"[mock {node}] $ {command}\n(simulated; MOCK_MODE)\n",
            "stderr": "",
        }

    def set_node_egress(self, instance_id, node, open):
        logger.info(f"[{instance_id}] 🎭 SIMULATING setup egress {'open' if open else 'close'} on {node}")
        return {"success": True, "egress": "open" if open else "closed"}

    def capture_traffic(self, instance_id, *, seconds=6, max_packets=200):
        logger.info(f"[{instance_id}] 🎭 SIMULATING MITM traffic capture ({seconds}s)")
        return {
            "success": True,
            "packets": 2,
            "flows": [
                {"src": "10.0.0.3", "dst": "10.0.0.2", "proto": "tcp", "sport": 51020, "dport": 80},
                {"src": "10.0.0.2", "dst": "10.0.0.3", "proto": "tcp", "sport": 80, "dport": 51020},
            ],
            "note": "simulated; MOCK_MODE",
        }
