"""
docker-local provider: container labs on the host Docker daemon (ADR-0003).

Each lab gets its own bridge network and one container per scenario node;
everything is tagged with `cyberguard.lab_id` labels so destroy() can find
and remove a lab without any local state. Deploys take seconds and cost
nothing — this is the workhorse for laptops, classrooms without a cloud,
CI end-to-end tests, and (later) agent-training loops.

Notes:
- `monitor`-role nodes are skipped for now: containerizing the Wazuh SOC is
  an open product question (backlog P7-5).
- Scenarios opt in via `requires.provider_class: container` (or `any`);
  VM-class scenarios are rejected with a clear error instead of a failed
  image pull.
- Needs access to a Docker daemon. In-container workers must mount
  /var/run/docker.sock (root-equivalent on the host — see SECURITY.md).
"""
import logging

from providers.base import RangeProvider

logger = logging.getLogger(__name__)

LABEL_LAB_ID = "cyberguard.lab_id"
LABEL_ROLE = "cyberguard.role"

# Keeps tool containers (kali etc.) alive when the scenario doesn't say how.
DEFAULT_ATTACKER_COMMAND = "sleep infinity"


class DockerLocalProvider(RangeProvider):
    name = "docker-local"

    def __init__(self, client=None):
        # Injectable for tests; lazily resolved so importing this module
        # never requires a running Docker daemon (or the docker package).
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _short(instance_id: str) -> str:
        return instance_id[:8]

    def _network_name(self, instance_id: str) -> str:
        return f"cyberguard-{self._short(instance_id)}"

    def _container_name(self, instance_id: str, role: str) -> str:
        return f"cg-{self._short(instance_id)}-{role}"

    @staticmethod
    def _supports(scenario_config: dict) -> bool:
        required = (scenario_config.get("requires") or {}).get("provider_class", "any")
        return required in ("container", "any")

    # --- interface -----------------------------------------------------------

    def deploy(self, scenario_config, instance_id, user_vars=None):
        if not self._supports(scenario_config):
            return {
                "success": False,
                "error": (
                    "Scenario requires VM-class infrastructure; the "
                    "docker-local provider only runs container scenarios "
                    "(requires.provider_class: container)"
                ),
            }
        if user_vars:
            logger.warning(f"[{instance_id}] docker-local ignores user_vars: {user_vars}")

        labels = {LABEL_LAB_ID: instance_id}
        net_name = self._network_name(instance_id)

        try:
            logger.info(f"[{instance_id}] Creating lab network {net_name}")
            self.client.networks.create(net_name, driver="bridge", labels=labels)

            containers = {}
            for vm in scenario_config.get("vms", []):
                role = vm.get("role", "node")
                if role == "monitor":
                    logger.info(
                        f"[{instance_id}] Skipping monitor node "
                        "(SOC containerization pending — backlog P7-5)"
                    )
                    continue

                run_kwargs = {
                    "image": vm["image"],
                    "name": self._container_name(instance_id, role),
                    "detach": True,
                    "network": net_name,
                    "labels": {**labels, LABEL_ROLE: role},
                }

                command = vm.get("command")
                if command is None and role == "attacker":
                    command = DEFAULT_ATTACKER_COMMAND
                if command is not None:
                    run_kwargs["command"] = command

                # Publish declared victim service ports on random host ports
                # so the trainee's browser can reach e.g. DVWA.
                if vm.get("ports"):
                    run_kwargs["ports"] = {f"{p}/tcp": None for p in vm["ports"]}

                logger.info(f"[{instance_id}] Starting {role}: {vm['image']}")
                containers[role] = self.client.containers.run(**run_kwargs)

            outputs = self._collect_outputs(instance_id, net_name, containers)
            logger.info(f"[{instance_id}] docker-local deployment complete")
            return {"success": True, "outputs": outputs}

        except Exception as e:
            logger.error(f"[{instance_id}] docker-local deploy failed: {e}")
            # Roll back whatever was created so nothing leaks.
            self.destroy(instance_id)
            return {"success": False, "error": str(e)}

    def _collect_outputs(self, instance_id, net_name, containers) -> dict:
        outputs = {"provider": self.name, "lab_network": net_name}

        key_prefix = {"attacker": "attack_vm", "victim": "victim_vm"}
        for role, container in containers.items():
            container.reload()  # IP/ports are only populated after start
            prefix = key_prefix.get(role, f"{role}_vm")

            nets = container.attrs["NetworkSettings"]["Networks"]
            ip = nets.get(net_name, {}).get("IPAddress", "")
            outputs[f"{prefix}_private_ip"] = ip
            outputs[f"{prefix}_name"] = container.name

            if role == "attacker":
                outputs["attack_vm_ssh_command"] = (
                    f"docker exec -it {container.name} /bin/bash"
                )

            # First published port (if any) → host-reachable URL
            ports = container.attrs["NetworkSettings"].get("Ports") or {}
            for bindings in ports.values():
                if bindings:
                    host_port = bindings[0]["HostPort"]
                    outputs[f"{prefix}_floating_ip"] = f"127.0.0.1:{host_port}"
                    if role == "victim":
                        outputs["victim_web_url"] = f"http://127.0.0.1:{host_port}"
                    break

        return outputs

    def destroy(self, instance_id):
        try:
            label_filter = {"label": f"{LABEL_LAB_ID}={instance_id}"}

            for container in self.client.containers.list(all=True, filters=label_filter):
                logger.info(f"[{instance_id}] Removing container {container.name}")
                container.remove(force=True)

            for network in self.client.networks.list(filters=label_filter):
                logger.info(f"[{instance_id}] Removing network {network.name}")
                network.remove()

            return {"success": True}
        except Exception as e:
            logger.error(f"[{instance_id}] docker-local destroy failed: {e}")
            return {"success": False, "error": str(e)}
