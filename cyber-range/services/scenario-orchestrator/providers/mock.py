"""
Mock provider: simulates a deployment with canned outputs.

Extracted from the original Orchestrator MOCK_MODE branch — keeps the demo,
tests and CI working with zero cloud cost. Output keys deliberately match
`infra/terraform/outputs.tf` so the UI renders identically in both modes.
"""
import hashlib
import logging
import time

from providers.base import RangeProvider
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

# Seconds of fake provisioning delay (visible status progression in the UI).
MOCK_DEPLOY_DELAY = 2
_TRANSFER_FILES: dict[tuple[str, str, str], bytes] = {}


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
            if node.get("sut_clone") or node.get("sut_bundle"):
                source = node.get("sut_clone") or node["sut_bundle"]
                fake_outputs[f"node_{name}_sut_source"] = source.get("path") or f"/opt/{name}"
                fake_outputs[f"node_{name}_setup_shell"] = f"docker exec -it nv-mock-{name} /bin/bash  # simulated"
            if node.get("ports"):
                fake_outputs[f"node_{name}_url"] = f"http://{ip}"

        return {"success": True, "outputs": fake_outputs}

    def destroy(self, instance_id):
        logger.info(f"[{instance_id}] 🎭 SIMULATING DESTROY...")
        return {"success": True}

    def observe_lifecycle(self, instance_id):
        return {"provider": self.name, "simulated": True, "nodes": []}

    def check_readiness(self, instance_id, outputs, policy):
        return {
            "ready": False,
            "status": "unverified",
            "error": "mock mode cannot prove application readiness",
        }

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

    def collect_monitor_signals(self, instance_id):
        # A simulated arena has no real workload to crash — report a healthy,
        # empty observation set so the monitor sweep stays quiet in MOCK_MODE.
        logger.info(f"[{instance_id}] 🎭 SIMULATING monitor collection (no signals)")
        return {"success": True, "observations": []}

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

    def write_transfer_file(self, instance_id, node, path, content):
        _TRANSFER_FILES[(instance_id, node, path)] = bytes(content)
        return {
            "success": True, "path": path,
            "container_path": f"/opt/nidavellir-transfer/{path}",
            "bytes": len(content),
        }

    def read_transfer_file(self, instance_id, node, path):
        try:
            return _TRANSFER_FILES[(instance_id, node, path)]
        except KeyError as exc:
            raise ValueError("transfer file was not found") from exc

    def browser_visit(
        self, instance_id, node, target_ip, port, scheme, path, params=None,
        *, wait_ms=1500, execution_marker=None,
    ):
        query = "&".join(f"{key}={value}" for key, value in (params or {}).items())
        url = f"{scheme}://{target_ip}:{port}{path}" + (f"?{query}" if query else "")
        return {
            "success": True,
            "url": url,
            "title": "Simulated browser",
            "rendered_dom": "<html><body>simulated; MOCK_MODE</body></html>",
            "dom_bytes": 48,
            "dom_sha256": "",
            "executed": False if execution_marker else None,
            "note": "simulated; MOCK_MODE",
        }

    def http_request(
        self, instance_id, node, target_ip, port, scheme, path, params=None,
        *, method="GET", headers=None, body=None,
    ):
        query = "&".join(f"{key}={value}" for key, value in (params or {}).items())
        url = f"{scheme}://{target_ip}:{port}{path}" + (f"?{query}" if query else "")
        logger.info(f"[{instance_id}] 🎭 SIMULATING http {method} {url}")
        payload = f"[mock {node}] {method} {url}\n(simulated; MOCK_MODE)\n".encode()
        return {
            "success": True,
            "url": url,
            "status": 200,
            "reason": "OK",
            "http_version": "HTTP/1.1",
            "headers": {"content-type": "text/plain"},
            "header_count": 1,
            "redirect_location": None,
            "body": payload.decode("utf-8", "replace"),
            "body_bytes": len(payload),
            "body_sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "truncated": False,
            "note": "simulated; MOCK_MODE",
        }
