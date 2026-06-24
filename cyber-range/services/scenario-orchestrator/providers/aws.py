"""
AWS provider: a per-arena VPC compiled from the v3 topology via a generic
``nodes[]`` OpenTofu module (ADR-0003; ROADMAP Phase 1 P1-2 + Phase 5 P5-2).

Unlike the legacy OpenStack driver (a frozen 3-VM template), this compiles an
arbitrary N-node scenario: one subnet per declared network ``segment``, one EC2
instance per ``node`` (``for_each``), everything tagged ``nidavellir:arena_id``.
Arenas get **no internet egress by default** — no IGW/NAT is created and the
security group is confined to the VPC CIDR — which is the Phase 2 containment
guarantee by construction.

Credentials/region come from the environment (``AWS_REGION``,
``AWS_ACCESS_KEY_ID``/``…SECRET_ACCESS_KEY``, or an instance role). The
``compile_vars`` mapping (scenario → ``arena.auto.tfvars.json``) is pure and
unit-tested; the real apply needs an AWS account, so it is exercised only when
credentials are present (mirrors the OpenStack driver's posture).
"""
import json
import logging
from pathlib import Path

import images
from config import AWS_TERRAFORM_TEMPLATE, RUNS_DIR
from providers.terraform_base import TerraformDriver
from redaction import redact_mapping
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

# size → EC2 instance type. Small footprint by default; the TTL reaper + the
# no-NAT/private-subnet posture keep cost bounded.
_INSTANCE_TYPE = {"small": "t3.small", "medium": "t3.medium", "large": "t3.large"}
_DEFAULT_INSTANCE_TYPE = "t3.small"

# Per-arena address space; segments get a /24 each under it.
_SEGMENT_CIDR = "10.20.{i}.0/24"

_ROLE_PREFIX = {"attacker": "attack_vm", "victim": "victim_vm", "monitor": "log_vm"}


class AWSProvider(TerraformDriver):
    name = "aws"
    infra_class = "vm"

    def _template_dir(self) -> Path:
        return AWS_TERRAFORM_TEMPLATE

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
                    "Scenario requires container-class infrastructure; the aws "
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
            # Surfaced as CLI -var overrides (rare for AWS); never logged raw.
            logger.info(f"[{instance_id}] aws user_var overrides: {redact_mapping(user_vars)}")
            return [arg for k, v in user_vars.items() for arg in ("-var", f"{k}={v}")]
        return []

    @classmethod
    def compile_vars(cls, scenario_config: dict, instance_id: str) -> dict:
        """Compile a v3 scenario into the AWS module's variables."""
        nodes = normalized_nodes(scenario_config)
        segments = cls._compile_segments(scenario_config, nodes)
        return {
            "arena_id": instance_id,
            "segments": segments,
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
        # Segments referenced by a node but not declared get a synthesized /24.
        for node in nodes:
            for seg in node.get("segments") or []:
                add(seg, None)
        # Nodes with no segment share a default subnet.
        if any(not (node.get("segments")) for node in nodes):
            add("default", None)
        return out

    @classmethod
    def _compile_node(cls, node: dict) -> dict:
        nv = {
            "name": node["name"],
            "role": node.get("role", "node"),
            "instance_type": _INSTANCE_TYPE.get(
                node.get("size", "small"), _DEFAULT_INSTANCE_TYPE
            ),
            "segments": list(node.get("segments") or ["default"]),
            "ports": list(node.get("ports") or []),
            "entrypoint": bool(node.get("entrypoint", False)),
            "ami": None,
            "ami_name": None,
            "ami_owner": None,
        }
        ref = images.resolve(node["image"], cls.name)
        if isinstance(ref, dict):
            nv["ami"] = ref.get("ami")
            nv["ami_name"] = ref.get("name")
            nv["ami_owner"] = ref.get("owner")
        elif isinstance(ref, str) and ref.startswith("ami-"):
            nv["ami"] = ref
        # else: unknown logical name with no AWS mapping → module falls back to
        # its default AMI (Ubuntu LTS).
        return nv

    # --- outputs --------------------------------------------------------------

    def _post_process_outputs(self, outputs: dict) -> dict:
        """Fan the module's per-node maps out into the flat ``node_<name>_*``
        contract the other providers emit, plus legacy role-prefixed keys for
        the first node of each canonical role (dashboard/mock parity)."""
        flat = {"provider": self.name}
        if outputs.get("arena_vpc_id"):
            flat["arena_vpc_id"] = outputs["arena_vpc_id"]

        ips = outputs.get("node_private_ips") or {}
        ids = outputs.get("node_instance_ids") or {}
        roles = outputs.get("node_roles") or {}

        seen_roles = set()
        for name, ip in ips.items():
            # The WebUI discovers nodes ONLY via `node_<name>_name` — without it an
            # AWS arena renders an empty nodes table/topology despite captured IPs.
            flat[f"node_{name}_name"] = ids.get(name, name)
            flat[f"node_{name}_private_ip"] = ip
            if name in ids:
                flat[f"node_{name}_instance_id"] = ids[name]

            prefix = _ROLE_PREFIX.get(roles.get(name))
            if prefix and roles.get(name) not in seen_roles:
                seen_roles.add(roles.get(name))
                flat[f"{prefix}_private_ip"] = ip
                if name in ids:
                    flat[f"{prefix}_name"] = ids[name]
        return flat
