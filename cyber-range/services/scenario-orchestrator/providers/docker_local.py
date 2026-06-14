"""
docker-local provider: container arenas on the host Docker daemon (ADR-0003).

Compiles a v3 scenario topology to Docker (ROADMAP Phase 1, P1-2): one bridge
network per declared network segment (per arena), one container per node,
attached to the networks of the segments it declares. A node may straddle
several segments; nodes that declare none share a per-arena default bridge.
Everything is tagged with `cyberguard.lab_id` so destroy() can find and remove
an arena without any local state. Deploys take seconds and cost nothing — the
workhorse for laptops, CI end-to-end tests, and cheap agent-test iteration.

Notes:
- `monitor`-role nodes are skipped for now: containerizing the Wazuh SOC is an
  open product question (backlog P7-5).
- Scenarios opt in via `requires.provider_class: container` (or `any`);
  VM-class scenarios are rejected with a clear error instead of a failed pull.
- Needs access to a Docker daemon. In-container workers must mount
  /var/run/docker.sock (root-equivalent on the host — see SECURITY.md).
"""
import logging

import images
from providers.base import RangeProvider
from redaction import redact_mapping
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

LABEL_LAB_ID = "cyberguard.lab_id"
LABEL_ROLE = "cyberguard.role"
LABEL_NODE = "cyberguard.node"

# Sentinel segment for nodes that declare none — realized as the per-arena
# default bridge, named WITHOUT a segment suffix so legacy/flat single-network
# scenarios keep their original `cyberguard-<short>` network name.
_DEFAULT_SEGMENT = "_default"

# Keeps tool containers (kali etc.) alive when the scenario doesn't say how.
DEFAULT_ATTACKER_COMMAND = "sleep infinity"

# Canonical roles get stable, dashboard-facing output key prefixes (the mock
# provider and WebUI expect these). Other roles are addressed per-node only.
_ROLE_PREFIX = {"attacker": "attack_vm", "victim": "victim_vm", "monitor": "log_vm"}


class DockerLocalProvider(RangeProvider):
    name = "docker-local"
    infra_class = "container"

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

    def _network_name(self, instance_id: str, segment: str) -> str:
        base = f"cyberguard-{self._short(instance_id)}"
        return base if segment == _DEFAULT_SEGMENT else f"{base}-{segment}"

    def _container_name(self, instance_id: str, node_name: str) -> str:
        return f"cg-{self._short(instance_id)}-{node_name}"

    @staticmethod
    def _supports(scenario_config: dict) -> bool:
        required = (scenario_config.get("requires") or {}).get("provider_class", "any")
        return required in ("container", "any")

    @staticmethod
    def _node_segments(node: dict) -> list[str]:
        """The segments a node attaches to, defaulting to the shared bridge."""
        return list(node.get("segments") or [_DEFAULT_SEGMENT])

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
            logger.warning(
                f"[{instance_id}] docker-local ignores user_vars: "
                f"{redact_mapping(user_vars)}"
            )

        labels = {LABEL_LAB_ID: instance_id}

        nodes = []
        for node in normalized_nodes(scenario_config):
            if node.get("role") == "monitor":
                logger.info(
                    f"[{instance_id}] Skipping monitor node {node.get('name')!r} "
                    "(SOC containerization pending — backlog P7-5)"
                )
                continue
            nodes.append(node)

        # One bridge per segment any kept node attaches to. Default segment
        # first so it stays the primary `lab_network`; the rest sorted for
        # deterministic ordering.
        wanted: list[str] = []
        for node in nodes:
            for seg in self._node_segments(node):
                if seg not in wanted:
                    wanted.append(seg)
        wanted.sort(key=lambda s: (s != _DEFAULT_SEGMENT, s))

        try:
            networks = {}
            for seg in wanted:
                net_name = self._network_name(instance_id, seg)
                logger.info(f"[{instance_id}] Creating arena network {net_name}")
                networks[seg] = self.client.networks.create(
                    net_name, driver="bridge", labels=labels
                )

            records = []
            for node in nodes:
                container = self._run_node(instance_id, node, networks, labels)
                records.append((node, container))

            outputs = self._collect_outputs(instance_id, networks, wanted, records)
            unhealthy = outputs.get("unhealthy_nodes")
            if unhealthy:
                # Don't pretend the arena is healthy: a node that exited the
                # instant it started (a target with no foreground service, a bad
                # image, a crash-on-boot) is the #1 docker-local gotcha. Surface
                # it loudly rather than reporting a silent, useless success.
                logger.warning(
                    f"[{instance_id}] deployment complete but these nodes exited "
                    f"immediately: {unhealthy} — see node_<name>_state / logs"
                )
            else:
                logger.info(f"[{instance_id}] docker-local deployment complete")
            return {"success": True, "outputs": outputs}

        except Exception as e:
            logger.error(f"[{instance_id}] docker-local deploy failed: {e}")
            # Roll back whatever was created so nothing leaks.
            self.destroy(instance_id)
            return {"success": False, "error": str(e)}

    def _run_node(self, instance_id, node, networks, labels):
        role = node.get("role", "node")
        primary, *extra = self._node_segments(node)
        image = images.resolve(node["image"], self.name)

        run_kwargs = {
            "image": image,
            "name": self._container_name(instance_id, node["name"]),
            "detach": True,
            "network": networks[primary].name,
            "labels": {**labels, LABEL_ROLE: role, LABEL_NODE: node["name"]},
        }

        command = node.get("command")
        if command is None and (role == "attacker" or node.get("entrypoint")):
            command = DEFAULT_ATTACKER_COMMAND
        if command is not None:
            run_kwargs["command"] = command

        # Publish declared service ports on random host ports so the operator's
        # browser can reach e.g. DVWA.
        if node.get("ports"):
            run_kwargs["ports"] = {f"{p}/tcp": None for p in node["ports"]}

        logger.info(
            f"[{instance_id}] Starting node {node['name']!r} ({role}): {image}"
        )
        container = self.client.containers.run(**run_kwargs)

        # Attach to any further segments this node straddles.
        for seg in extra:
            networks[seg].connect(container)
        return container

    def _collect_outputs(self, instance_id, networks, wanted, records) -> dict:
        outputs = {
            "provider": self.name,
            "lab_network": networks[wanted[0]].name if wanted else None,
            "lab_networks": [networks[s].name for s in wanted],
        }

        seen_roles = set()
        unhealthy = []
        for node, container in records:
            container.reload()  # IP/ports/state are only populated after start
            role = node.get("role", "node")
            name = node["name"]
            primary_net = networks[self._node_segments(node)[0]].name

            # Liveness: a node that already exited (a target with no foreground
            # service, a crash-on-boot, a bad image) is the #1 docker-local
            # gotcha. Record its state so a dead box is diagnosable, not silent.
            state = (container.attrs.get("State") or {}).get("Status", "running")
            outputs[f"node_{name}_state"] = state
            if state != "running":
                unhealthy.append(name)
                logger.warning(
                    f"[{instance_id}] node {name!r} ({role}) is {state} right "
                    f"after start — last logs: {self._tail_logs(container)}"
                )

            nets = container.attrs["NetworkSettings"]["Networks"]
            ip = nets.get(primary_net, {}).get("IPAddress", "")
            ssh = f"docker exec -it {container.name} /bin/bash"
            is_foothold = role == "attacker" or bool(node.get("entrypoint"))

            # First published port (if any) → host-reachable URL.
            floating = url = None
            ports = container.attrs["NetworkSettings"].get("Ports") or {}
            for bindings in ports.values():
                if bindings:
                    host_port = bindings[0]["HostPort"]
                    floating = f"127.0.0.1:{host_port}"
                    url = f"http://127.0.0.1:{host_port}"
                    break

            # Per-node outputs — always emitted, so repeated roles and N-node
            # topologies are fully addressable.
            outputs[f"node_{name}_name"] = container.name
            outputs[f"node_{name}_private_ip"] = ip
            if is_foothold:
                outputs[f"node_{name}_ssh_command"] = ssh
            if floating:
                outputs[f"node_{name}_floating_ip"] = floating
                outputs[f"node_{name}_url"] = url

            # Legacy role-prefixed outputs for the FIRST node of each canonical
            # role (the dashboard + mock-parity contract).
            prefix = _ROLE_PREFIX.get(role)
            if prefix and role not in seen_roles:
                seen_roles.add(role)
                outputs[f"{prefix}_private_ip"] = ip
                outputs[f"{prefix}_name"] = container.name
                if is_foothold:
                    outputs[f"{prefix}_ssh_command"] = ssh
                if floating:
                    outputs[f"{prefix}_floating_ip"] = floating
                    if role == "victim":
                        outputs["victim_web_url"] = url

        if unhealthy:
            outputs["unhealthy_nodes"] = unhealthy
        return outputs

    @staticmethod
    def _tail_logs(container, limit: int = 500) -> str:
        """Best-effort last log lines from a (likely exited) container."""
        try:
            raw = container.logs(tail=20)
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            return text.strip()[-limit:]
        except Exception:
            return "<no logs>"

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
