"""
Scenario schema v3 — the dynamic N-node topology spec (ROADMAP Phase 1, P1-1).

A scenario is a provider-agnostic, data-defined topology: arbitrary ``nodes[]``
on named network ``segments[]``, plus ``objectives`` and optional ``agents[]``
stance bindings — not a frozen victim/attacker/monitor trio. One spec is meant
to compile to any provider (docker-local, openstack, aws) through the provider
abstraction (ADR-0003).

This module is the canonical in-memory representation (``ScenarioSpec``,
Pydantic v2) plus the normalization that accepts BOTH the new v3
``nodes[]``/``segments[]`` shape and the legacy ``vms[]`` shape, so existing
scenarios and the provider drivers keep working through the migration.

Validation split:
- **Hard** structural problems raise ``pydantic.ValidationError``: a node with
  no image, a node attached to an undefined segment, an agent bound to a
  missing node, duplicate node/segment names, an empty topology.
- **Soft** issues that don't prevent a deploy are surfaced by
  ``ScenarioSpec.warnings()`` (e.g. an attacker stance whose node isn't an
  entrypoint, or a segment with no nodes) — the scenario still loads.

``normalized_nodes()`` / ``primary_cidr()`` are the lightweight, non-validating
accessors the provider drivers use so they consume one node shape regardless of
which schema the scenario was authored in.
"""
from __future__ import annotations

import ipaddress
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "cyberguard/v3"

# Slug for node/segment names: lowercase, starts alphanumeric, then
# alphanumeric/'-'/'_', 1-63 chars. Mirrors SCENARIO_ID_RE in scenarios.py so
# names are safe as container names, terraform resource keys, etc.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

# Roles the platform attaches behaviour to (foothold for the attacker stance,
# service publishing for victims, sensor feed for the defender stance). Roles
# are NOT restricted to this set — a scenario may declare any slug role (GOAD
# uses domain-controller, web, etc.); these are just the ones drivers special-
# case today.
CANONICAL_ROLES = ("attacker", "victim", "monitor")


class ProviderClass(str, Enum):
    vm = "vm"
    container = "container"
    any = "any"


class Stance(str, Enum):
    attacker = "attacker"
    mitm = "mitm"
    defender = "defender"


def _check_slug(value: str, what: str) -> str:
    if not _SLUG_RE.match(value):
        raise ValueError(
            f"{what} {value!r} is not a valid slug (lowercase alphanumeric, "
            "'-' or '_', 1-63 chars, must start with a letter or digit)"
        )
    return value


def _slugify(value: str) -> str:
    """Best-effort slug for legacy free-text names (network names, etc.)."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return slug or "default"


class Segment(BaseModel):
    """A named network segment nodes can be attached to."""

    model_config = ConfigDict(extra="forbid")

    name: str
    cidr: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_is_slug(cls, v: str) -> str:
        return _check_slug(v, "segment name")

    @field_validator("cidr")
    @classmethod
    def _cidr_is_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError as e:
            raise ValueError(f"invalid CIDR {v!r}: {e}") from None
        return v


class Node(BaseModel):
    """One machine in the topology — a container or a VM, per provider."""

    model_config = ConfigDict(extra="ignore")

    name: str
    role: str = "node"
    image: str
    size: str = "small"
    segments: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    #: marks the foothold an attacker stance attaches to (Phase 2 gateway).
    entrypoint: bool = False
    #: container/VM entrypoint override (e.g. "sleep infinity" for tool boxes).
    command: str | None = None
    #: informational only — rendered in briefings/UI, not load-bearing.
    services: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_is_slug(cls, v: str) -> str:
        return _check_slug(v, "node name")

    @field_validator("role")
    @classmethod
    def _role_is_slug(cls, v: str) -> str:
        return _check_slug(v, "node role")

    @field_validator("ports")
    @classmethod
    def _ports_in_range(cls, v: list[int]) -> list[int]:
        for p in v:
            if not 1 <= p <= 65535:
                raise ValueError(f"port {p} out of range 1-65535")
        return v


class AgentBinding(BaseModel):
    """Wires a BYO agent stance onto a node (consumed by the Phase 2 gateway)."""

    model_config = ConfigDict(extra="forbid")

    stance: Stance
    node: str


class Objective(BaseModel):
    """A scored goal. Full scoring is Phase 4; this keeps the authoring shape."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    description: str
    points: int | None = None


class Requires(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_class: ProviderClass = ProviderClass.any


class Network(BaseModel):
    model_config = ConfigDict(extra="ignore")

    segments: list[Segment] = Field(default_factory=list)


class ScenarioSpec(BaseModel):
    """A validated v3 scenario: an N-node topology over named segments."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_version: str = Field(default=SCHEMA_VERSION, alias="schema")
    name: str
    title: str | None = None
    description: str | None = None
    difficulty: str = "unknown"
    requires: Requires = Field(default_factory=Requires)
    network: Network = Field(default_factory=Network)
    nodes: list[Node] = Field(min_length=1)
    agents: list[AgentBinding] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)
    ttl_hours: int | None = None
    tags: list[str] = Field(default_factory=list)

    # --- cross-field structural checks (hard errors) ----------------------

    @model_validator(mode="after")
    def _check_topology(self) -> ScenarioSpec:
        node_names = [n.name for n in self.nodes]
        dupes = {n for n in node_names if node_names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate node name(s): {sorted(dupes)}")

        seg_names = [s.name for s in self.network.segments]
        seg_dupes = {s for s in seg_names if seg_names.count(s) > 1}
        if seg_dupes:
            raise ValueError(f"duplicate segment name(s): {sorted(seg_dupes)}")

        defined = set(seg_names)
        for node in self.nodes:
            unknown = [s for s in node.segments if s not in defined]
            if unknown:
                raise ValueError(
                    f"node {node.name!r} references undefined segment(s) "
                    f"{unknown}; defined segments: {sorted(defined) or '[]'}"
                )

        known_nodes = set(node_names)
        for binding in self.agents:
            if binding.node not in known_nodes:
                raise ValueError(
                    f"agent stance {binding.stance.value!r} bound to unknown "
                    f"node {binding.node!r}; nodes: {sorted(known_nodes)}"
                )
        return self

    # --- soft advisories (do not block a deploy) --------------------------

    def warnings(self) -> list[str]:
        out: list[str] = []
        entrypoints = {n.name for n in self.nodes if n.entrypoint}
        for binding in self.agents:
            if binding.stance is Stance.attacker and binding.node not in entrypoints:
                out.append(
                    f"attacker stance is bound to node {binding.node!r} which is "
                    "not marked entrypoint: true"
                )
        if any(b.stance is Stance.attacker for b in self.agents) and not entrypoints:
            out.append("an attacker stance is declared but no node is an entrypoint")

        attached = {s for n in self.nodes for s in n.segments}
        for seg in self.network.segments:
            if seg.name not in attached:
                out.append(f"segment {seg.name!r} has no nodes attached")
        return out

    # --- construction from raw YAML (v3 or legacy) ------------------------

    @classmethod
    def from_raw(cls, raw: dict, *, scenario_id: str | None = None) -> ScenarioSpec:
        """Build a spec from a raw scenario dict, normalizing the legacy
        ``vms[]``/single-``network`` shape into v3 ``nodes[]``/``segments[]``."""
        data = dict(raw or {})

        if "nodes" not in data and "vms" in data:
            data["nodes"] = [_legacy_vm_to_node(vm) for vm in data.get("vms") or []]

        net = dict(data.get("network") or {})
        if "segments" not in net:
            seg = _legacy_segment(net)
            net["segments"] = [seg] if seg else []
            data["network"] = net
            # Attach nodes that didn't declare a segment to the default one, so
            # the topology stays connected after the legacy flattening.
            if seg:
                for node in data.get("nodes") or []:
                    if isinstance(node, dict) and not node.get("segments"):
                        node["segments"] = [seg["name"]]

        if "objectives" not in data:
            meta_obj = (data.get("metadata") or {}).get("objectives")
            if meta_obj:
                data["objectives"] = [_coerce_objective(o) for o in meta_obj]

        if "tags" not in data:
            tags = (data.get("metadata") or {}).get("tags")
            if tags:
                data["tags"] = list(tags)

        if not data.get("name") and scenario_id:
            data["name"] = scenario_id

        return cls.model_validate(data)


# --- legacy normalization helpers (shared with the provider drivers) ---------


def _legacy_vm_to_node(vm: dict) -> dict:
    node: dict = {
        "name": vm.get("name") or vm.get("role") or "node",
        "role": vm.get("role", "node"),
        "image": vm.get("image"),
    }
    if vm.get("segments"):
        node["segments"] = list(vm["segments"])
    if vm.get("ports"):
        node["ports"] = list(vm["ports"])
    if vm.get("command") is not None:
        node["command"] = vm["command"]
    # The legacy attacker box is the foothold; mark it for the gateway.
    if vm.get("role") == "attacker":
        node["entrypoint"] = True
    if vm.get("services"):
        node["services"] = [str(s) for s in vm["services"]]
    if vm.get("tools"):
        node["tools"] = [str(t) for t in vm["tools"]]
    # Carried through for the still-fixed OpenStack flavor mapping (P1-2 will
    # replace this with a per-provider size→flavor/AMI map). Ignored by the
    # ScenarioSpec model itself (extra="ignore").
    if vm.get("flavor"):
        node["flavor"] = vm["flavor"]
    return node


def _legacy_segment(net: dict) -> dict | None:
    if not net:
        return None
    seg: dict = {"name": _slugify(net.get("name") or "default")}
    if net.get("cidr"):
        seg["cidr"] = net["cidr"]
    return seg


def _coerce_objective(obj) -> dict:
    if isinstance(obj, str):
        return {"description": obj}
    if isinstance(obj, dict):
        return obj
    return {"description": str(obj)}


def _canonical_node(node: dict) -> dict:
    """Fill defaults for a v3 node dict (non-validating)."""
    canonical = {
        "name": node.get("name", "node"),
        "role": node.get("role", "node"),
        "image": node.get("image"),
        "size": node.get("size", "small"),
        "segments": list(node.get("segments") or []),
        "ports": list(node.get("ports") or []),
        "entrypoint": bool(node.get("entrypoint", False)),
        "command": node.get("command"),
        "services": list(node.get("services") or []),
        "tools": list(node.get("tools") or []),
    }
    if node.get("flavor"):
        canonical["flavor"] = node["flavor"]
    return canonical


def normalized_nodes(scenario_config: dict) -> list[dict]:
    """Uniform node dicts from either a v3 ``nodes[]`` or legacy ``vms[]``
    config. Used by provider drivers so they consume one shape. Does NOT
    validate — that is ``scenarios.load_scenario_spec()``'s job."""
    if scenario_config.get("nodes"):
        return [_canonical_node(n) for n in scenario_config["nodes"]]
    return [_legacy_vm_to_node(vm) for vm in scenario_config.get("vms") or []]


def primary_cidr(scenario_config: dict) -> str | None:
    """The scenario's main CIDR: legacy ``network.cidr``, else the first
    segment's cidr. Used by the (still fixed-topology) OpenStack driver."""
    net = scenario_config.get("network") or {}
    if net.get("cidr"):
        return net["cidr"]
    for seg in net.get("segments") or []:
        if isinstance(seg, dict) and seg.get("cidr"):
            return seg["cidr"]
    return None


def json_schema() -> dict:
    """The published JSON Schema for v3 scenarios (keyed by alias, so the
    top-level ``schema`` field appears as authors write it)."""
    return ScenarioSpec.model_json_schema(by_alias=True)


if __name__ == "__main__":
    import json

    print(json.dumps(json_schema(), indent=2))
