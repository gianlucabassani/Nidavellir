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
    """The bound stance is not permitted to call this tool."""


@dataclass
class GatewayContext:
    client: RestClient
    session: Session
    trace_dir: str | None = None


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
