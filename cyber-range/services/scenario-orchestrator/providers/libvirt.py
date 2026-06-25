"""
libvirt/QEMU provider: a per-arena set of local VMs compiled from the v3 topology
via a generic ``nodes[]`` OpenTofu module (ADR-0003; the local-VM enabler — the
vm-class peer of ``docker-local``).

Like the AWS driver, it compiles an arbitrary N-node scenario: one **isolated**
libvirt network per declared ``segment`` (no forwarding → no internet egress by
construction, the Phase-2 containment guarantee), one ``libvirt_domain`` per
``node`` (``for_each``), each named/tagged ``nv-<arena_id>-<node>``. It reuses the
``TerraformDriver`` spine, so the SAME provider-agnostic spec compiles to
libvirt-local here or to AWS/OpenStack in the cloud.

The hypervisor URI + default cloud image come from the environment (``LIBVIRT_URI``,
``LIBVIRT_BASE_IMAGE``, ``LIBVIRT_POOL``). ``compile_vars`` (scenario →
``arena.auto.tfvars.json``) is pure and unit-tested; the real ``apply`` needs
libvirtd + KVM + the dmacvicar/libvirt plugin, so it is exercised only where that
tooling is present (mirrors the AWS/OpenStack posture).

INCREMENT 1 = deploy/destroy + var-compilation (AWS/OpenStack parity). Like those
VM drivers, ``exec_in_node`` / ``set_node_egress`` are NOT implemented here — VM
arenas are deploy-only until SSH/guest-agent exec + libvirt-network egress land
(increment 2). See ``.agent/research/local-vm-provider-qemu.md``.
"""
import json
import logging
from pathlib import Path

import config
import images
from config import LIBVIRT_TERRAFORM_TEMPLATE, RUNS_DIR
from providers.terraform_base import TerraformDriver
from redaction import redact_mapping
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

# size → (memory MiB, vcpu). Small footprint by default; the TTL reaper bounds it.
_SIZE = {"small": (1024, 1), "medium": (2048, 2), "large": (4096, 2)}
_DEFAULT_SIZE = "small"

# Per-arena address space; segments get a /24 each under it.
_SEGMENT_CIDR = "10.30.{i}.0/24"

_ROLE_PREFIX = {"attacker": "attack_vm", "victim": "victim_vm", "monitor": "log_vm"}

# A node `image` is used as a concrete disk source only when it looks like one
# (URL / path / disk-image suffix); logical names (kali/ubuntu/dvwa) have no
# per-image qcow2 map yet → fall back to the default base image.
_IMG_SUFFIXES = (".qcow2", ".img", ".raw")


def _is_disk_source(ref: object) -> bool:
    return isinstance(ref, str) and (
        "://" in ref or ref.startswith("/") or ref.endswith(_IMG_SUFFIXES)
    )


class LibvirtProvider(TerraformDriver):
    name = "libvirt"
    infra_class = "vm"

    def _template_dir(self) -> Path:
        return LIBVIRT_TERRAFORM_TEMPLATE

    def _runs_dir(self) -> Path:
        return RUNS_DIR

    @staticmethod
    def _supports(scenario_config: dict) -> bool:
        required = (scenario_config.get("requires") or {}).get("provider_class", "any")
        return required in ("vm", "any")

    def deploy(self, scenario_config, instance_id, user_vars=None):
        if not self._supports(scenario_config):
            return {
                "success": False,
                "error": (
                    "Scenario requires container-class infrastructure; the libvirt "
                    "provider only deploys VM-class scenarios "
                    "(requires.provider_class: vm)"
                ),
            }
        return super().deploy(scenario_config, instance_id, user_vars)

    # --- variable compilation (pure; unit-tested) ----------------------------

    def _write_vars(self, work_dir, scenario_config, instance_id, user_vars):
        tfvars = self.compile_vars(scenario_config, instance_id)
        (Path(work_dir) / "arena.auto.tfvars.json").write_text(
            json.dumps(tfvars, indent=2)
        )
        if user_vars:
            logger.info(
                f"[{instance_id}] libvirt user_var overrides: {redact_mapping(user_vars)}"
            )
            return [arg for k, v in user_vars.items() for arg in ("-var", f"{k}={v}")]
        return []

    @classmethod
    def compile_vars(cls, scenario_config: dict, instance_id: str) -> dict:
        """Compile a v3 scenario into the libvirt module's variables."""
        nodes = normalized_nodes(scenario_config)
        return {
            "arena_id": instance_id,
            "libvirt_uri": config.LIBVIRT_URI,
            "pool": config.LIBVIRT_POOL,
            "base_image": config.LIBVIRT_BASE_IMAGE,
            "segments": cls._compile_segments(scenario_config, nodes),
            "nodes": [cls._compile_node(n) for n in nodes],
        }

    @staticmethod
    def _compile_segments(scenario_config: dict, nodes: list[dict]) -> list[dict]:
        declared = (scenario_config.get("network") or {}).get("segments") or []
        out: list[dict] = []
        seen: set[str] = set()

        def add(name: str, cidr: str | None):
            if not name or name in seen:
                return
            seen.add(name)
            out.append({"name": name, "cidr": cidr or _SEGMENT_CIDR.format(i=len(out))})

        for seg in declared:
            add(seg.get("name"), seg.get("cidr"))
        for node in nodes:
            for seg in node.get("segments") or []:
                add(seg, None)
        if any(not (node.get("segments")) for node in nodes):
            add("default", None)
        return out

    @classmethod
    def _compile_node(cls, node: dict) -> dict:
        memory, vcpu = _SIZE.get(node.get("size", _DEFAULT_SIZE), _SIZE[_DEFAULT_SIZE])
        ref = images.resolve(node["image"], cls.name)
        return {
            "name": node["name"],
            "role": node.get("role", "node"),
            "memory": memory,
            "vcpu": vcpu,
            "segments": list(node.get("segments") or ["default"]),
            "ports": list(node.get("ports") or []),
            "entrypoint": bool(node.get("entrypoint", False)),
            # Concrete source if the image is a real disk source, else null →
            # the module uses base_image (a cloud image with cloud-init).
            "image": ref if _is_disk_source(ref) else None,
        }

    # --- outputs --------------------------------------------------------------

    def _post_process_outputs(self, outputs: dict) -> dict:
        """Fan the module's per-node maps out into the flat ``node_<name>_*``
        contract (mirrors the AWS driver), plus legacy role-prefixed keys for the
        first node of each canonical role (dashboard/mock parity)."""
        flat = {"provider": self.name}
        ips = outputs.get("node_private_ips") or {}
        ids = outputs.get("node_instance_ids") or {}
        roles = outputs.get("node_roles") or {}

        seen_roles = set()
        for name, did in ids.items():
            ip = ips.get(name, "")
            # The WebUI discovers nodes ONLY via node_<name>_name.
            flat[f"node_{name}_name"] = f"nv-{name}"
            flat[f"node_{name}_domain_id"] = did
            if ip:
                flat[f"node_{name}_private_ip"] = ip

            prefix = _ROLE_PREFIX.get(roles.get(name))
            if prefix and roles.get(name) not in seen_roles:
                seen_roles.add(roles.get(name))
                flat[f"{prefix}_name"] = f"nv-{name}"
                if ip:
                    flat[f"{prefix}_private_ip"] = ip
        return flat
