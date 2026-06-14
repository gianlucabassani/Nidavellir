"""
Lifecycle tool logic — pure functions over a GatewayContext.

These are the bodies the MCP `@tool` wrappers in `server.py` delegate to. They
are transport-agnostic and fully unit-testable with a fake REST client. Each
call is gated against the session's stance allow-list and recorded to the trace.
"""
import logging
import uuid
from dataclasses import dataclass

from gateway import trace
from gateway.rest_client import RestClient
from gateway.session import Session

logger = logging.getLogger(__name__)


class ToolNotAllowed(Exception):
    """The bound stance is not permitted to call this tool / touch this node."""


class BudgetExceeded(Exception):
    """The session's command/step budget is exhausted."""


@dataclass
class GatewayContext:
    client: RestClient
    session: Session
    trace_dir: str | None = None
    step_budget: int = 0  # 0 = unlimited
    steps_used: int = 0


def _guard(ctx: GatewayContext, tool: str) -> None:
    if not ctx.session.can_use(tool):
        stance = ctx.session.stance.value if ctx.session.stance else "unbound"
        raise ToolNotAllowed(f"stance {stance!r} may not call {tool!r}")


def _trace(ctx: GatewayContext, tool: str, args: dict, ok: bool, arena_id: str | None = None):
    trace.record(
        ctx.trace_dir,
        agent_id=ctx.session.agent_id,
        stance=ctx.session.stance.value if ctx.session.stance else None,
        tool=tool,
        args=args,
        ok=ok,
        arena_id=arena_id,
    )


def _charge_step(ctx: GatewayContext) -> None:
    if ctx.step_budget and ctx.steps_used >= ctx.step_budget:
        raise BudgetExceeded(
            f"command/step budget ({ctx.step_budget}) exhausted for this session"
        )
    ctx.steps_used += 1


def _node_names(outputs: dict) -> set[str]:
    return {
        k[len("node_"):-len("_name")]
        for k in outputs
        if k.startswith("node_") and k.endswith("_name")
    }


def _footholds(outputs: dict) -> list[str]:
    # A foothold is any node the provider exposed a shell command for.
    return sorted(
        k[len("node_"):-len("_ssh_command")]
        for k in outputs
        if k.startswith("node_") and k.endswith("_ssh_command")
    )


def _resolve_foothold(ctx: GatewayContext, arena_id: str, node: str | None) -> str:
    """The node an attacker may exec from — enforces foothold-only scope."""
    outputs = ctx.client.status(ctx.session.api_key, arena_id).get("outputs", {})
    footholds = _footholds(outputs)
    if node is not None:
        if node not in footholds:
            raise ToolNotAllowed(
                f"the attacker stance may only run commands on a foothold node "
                f"{footholds or '[]'}, not {node!r}"
            )
        return node
    if len(footholds) == 1:
        return footholds[0]
    if not footholds:
        raise ToolNotAllowed(f"arena {arena_id!r} has no foothold node to exec from")
    raise ValueError(f"multiple footholds {footholds}; pass node= to choose one")


def _new_arena_name() -> str:
    # A friendly, instance-id-regex-safe label (lowercase, hyphens, <=40).
    return f"arena-{uuid.uuid4().hex[:8]}"


def list_scenarios(ctx: GatewayContext) -> dict:
    _guard(ctx, "list_scenarios")
    data = ctx.client.list_scenarios(ctx.session.api_key)
    _trace(ctx, "list_scenarios", {}, ok=True)
    return data


def deploy_arena(ctx: GatewayContext, scenario: str, provider: str | None = None) -> dict:
    _guard(ctx, "deploy_arena")
    name = _new_arena_name()
    try:
        res = ctx.client.deploy(ctx.session.api_key, scenario, name, provider)
    except Exception:
        _trace(ctx, "deploy_arena", {"scenario": scenario, "provider": provider}, ok=False)
        raise
    # The orchestrator's response `instance_id` is the canonical system id used
    # for subsequent status/destroy; the friendly name is just a label.
    arena_id = (res or {}).get("instance_id", name)
    _trace(
        ctx, "deploy_arena",
        {"scenario": scenario, "provider": provider, "name": name},
        ok=True, arena_id=arena_id,
    )
    return {"arena_id": arena_id, "name": name, "status": (res or {}).get("status", "accepted")}


def arena_status(ctx: GatewayContext, arena_id: str) -> dict:
    _guard(ctx, "arena_status")
    res = ctx.client.status(ctx.session.api_key, arena_id)
    _trace(ctx, "arena_status", {}, ok=True, arena_id=arena_id)
    return res


def destroy_arena(ctx: GatewayContext, arena_id: str) -> dict:
    _guard(ctx, "destroy_arena")
    res = ctx.client.destroy(ctx.session.api_key, arena_id)
    _trace(ctx, "destroy_arena", {}, ok=True, arena_id=arena_id)
    return {"arena_id": arena_id, "status": (res or {}).get("status", "accepted")}


def get_briefing(ctx: GatewayContext, arena_id: str) -> dict:
    """The engagement brief for the bound stance: arena status, the scenario
    summary, the stance, and the rules of engagement. (The richer per-stance
    briefing.md + scope.json ride with the scenario-package layout, P1-3.)"""
    _guard(ctx, "get_briefing")
    status = ctx.client.status(ctx.session.api_key, arena_id)
    registry = {s["id"]: s for s in ctx.client.list_scenarios(ctx.session.api_key).get("scenarios", [])}
    summary = registry.get(status.get("scenario"), {})
    briefing = {
        "arena_id": arena_id,
        "stance": ctx.session.stance.value if ctx.session.stance else None,
        "status": status.get("status"),
        "scenario": summary,
        "rules_of_engagement": [
            "Targets are limited to this arena's own nodes — nothing else is in scope.",
            "Arena segments have no internet egress (provider-enforced containment).",
            "Every tool call is authenticated, scoped, and recorded to an audit trace.",
        ],
        "outputs": status.get("outputs", {}),
    }
    _trace(ctx, "get_briefing", {}, ok=True, arena_id=arena_id)
    return briefing


# --- attacker stance ---------------------------------------------------------


def get_topology(ctx: GatewayContext, arena_id: str) -> dict:
    """The arena's nodes (name, private IP, web URL, state, foothold?) and
    networks — the attacker's map of what's reachable."""
    _guard(ctx, "get_topology")
    outputs = ctx.client.status(ctx.session.api_key, arena_id).get("outputs", {})
    footholds = set(_footholds(outputs))
    nodes = [
        {
            "node": name,
            "private_ip": outputs.get(f"node_{name}_private_ip"),
            "url": outputs.get(f"node_{name}_url"),
            "state": outputs.get(f"node_{name}_state"),
            "foothold": name in footholds,
        }
        for name in sorted(_node_names(outputs))
    ]
    _trace(ctx, "get_topology", {}, ok=True, arena_id=arena_id)
    return {"arena_id": arena_id, "networks": outputs.get("lab_networks", []), "nodes": nodes}


def list_targets(ctx: GatewayContext, arena_id: str) -> dict:
    """Just the in-scope targets (every non-foothold node) with how to reach
    them — the shortlist an attacker actually engages."""
    _guard(ctx, "list_targets")
    outputs = ctx.client.status(ctx.session.api_key, arena_id).get("outputs", {})
    footholds = set(_footholds(outputs))
    targets = [
        {
            "node": name,
            "private_ip": outputs.get(f"node_{name}_private_ip"),
            "url": outputs.get(f"node_{name}_url"),
            "state": outputs.get(f"node_{name}_state"),
        }
        for name in sorted(_node_names(outputs))
        if name not in footholds
    ]
    _trace(ctx, "list_targets", {}, ok=True, arena_id=arena_id)
    return {"targets": targets}


def run_command(
    ctx: GatewayContext,
    arena_id: str,
    command: str,
    node: str | None = None,
    timeout: int = 30,
) -> dict:
    """Run a shell command from the arena's foothold node and return its
    output. Foothold-only (attacker scope), budget-charged, fully traced.

    `node` defaults to the arena's single foothold; pass it explicitly when an
    arena has more than one. Every command is also audited server-side (it
    feeds the future defender stance)."""
    _guard(ctx, "run_command")
    _charge_step(ctx)
    foothold = _resolve_foothold(ctx, arena_id, node)
    try:
        res = ctx.client.exec_command(ctx.session.api_key, arena_id, foothold, command, timeout)
    except Exception:
        _trace(ctx, "run_command",
               {"node": foothold, "command": command[:512]}, ok=False, arena_id=arena_id)
        raise
    _trace(
        ctx, "run_command",
        {"node": foothold, "command": command[:512], "exit_code": res.get("exit_code")},
        ok=True, arena_id=arena_id,
    )
    return res
