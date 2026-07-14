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


def _check_budget(ctx: GatewayContext) -> None:
    """Raise if the step budget is exhausted. The budget is *consumed* only after
    a successful action (the tool bodies increment ``steps_used`` post-exec), so a
    transient failure — orchestrator down, foothold-resolution error — does not
    permanently burn the agent's budget on a command that never ran."""
    if ctx.step_budget and ctx.steps_used >= ctx.step_budget:
        raise BudgetExceeded(
            f"command/step budget ({ctx.step_budget}) exhausted for this session"
        )


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


def scaffold_scenario(ctx: GatewayContext, prompt: str,
                      provider_class: str | None = None) -> dict:
    """Operator authoring: generate a candidate v3 scenario from a prompt using
    the operator's own connected model. Proxies the orchestrator's review gate
    (POST /scenarios/generate) — returns {valid, spec, topology, errors,
    suggested_id, ...} and does NOT deploy or save. Operator-only (the
    orchestrator rejects non-operator keys)."""
    _guard(ctx, "scaffold_scenario")
    try:
        res = ctx.client.generate_scenario(ctx.session.api_key, prompt, provider_class)
    except Exception:
        _trace(ctx, "scaffold_scenario", {"provider_class": provider_class}, ok=False)
        raise
    _trace(ctx, "scaffold_scenario",
           {"provider_class": provider_class, "valid": bool((res or {}).get("valid"))}, ok=True)
    return res


def import_scenario(ctx: GatewayContext, spec, scenario_id: str | None = None,
                    overwrite: bool = False) -> dict:
    """Operator authoring: persist a reviewed v3 spec as a reusable pack (proxies
    POST /scenarios). Use after scaffold_scenario returns a valid spec you've
    reviewed. Operator-only."""
    _guard(ctx, "import_scenario")
    try:
        res = ctx.client.import_scenario(ctx.session.api_key, spec, scenario_id, overwrite)
    except Exception:
        _trace(ctx, "import_scenario", {"id": scenario_id, "overwrite": overwrite}, ok=False)
        raise
    _trace(ctx, "import_scenario",
           {"id": (res or {}).get("id", scenario_id), "overwrite": overwrite}, ok=True)
    return res


def destroy_arena(ctx: GatewayContext, arena_id: str) -> dict:
    _guard(ctx, "destroy_arena")
    res = ctx.client.destroy(ctx.session.api_key, arena_id)
    _trace(ctx, "destroy_arena", {}, ok=True, arena_id=arena_id)
    return {"arena_id": arena_id, "status": (res or {}).get("status", "accepted")}


def announce_agent(ctx: GatewayContext, arena_id: str, model: str, provider: str) -> dict:
    """Declare the connected agent's model + provider for the operator console's
    'connected model' indicator. Stance is taken from the bound session. This is
    harness plumbing (telemetry), not an agent action — the raw key is never sent
    in the body, only forwarded as the auth header by the REST client."""
    _guard(ctx, "announce_agent")
    stance = ctx.session.stance.value if ctx.session.stance else None
    try:
        res = ctx.client.announce_agent(ctx.session.api_key, arena_id, model, provider, stance)
    except Exception:
        _trace(ctx, "announce_agent",
               {"model": model, "provider": provider}, ok=False, arena_id=arena_id)
        raise
    _trace(ctx, "announce_agent",
           {"model": model, "provider": provider}, ok=True, arena_id=arena_id)
    return res


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
    _check_budget(ctx)
    # Resolve the foothold INSIDE the try so a status-lookup failure is traced
    # (ok=False) instead of escaping untraced, and so it doesn't run after budget
    # has been consumed.
    try:
        foothold = _resolve_foothold(ctx, arena_id, node)
        res = ctx.client.exec_command(ctx.session.api_key, arena_id, foothold, command, timeout)
    except Exception:
        _trace(ctx, "run_command",
               {"node": node, "command": command[:512]}, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1  # consume budget only on a command that actually ran
    _trace(
        ctx, "run_command",
        {"node": foothold, "command": command[:512], "exit_code": res.get("exit_code")},
        ok=True, arena_id=arena_id,
    )
    return res


def report_finding(
    ctx: GatewayContext,
    arena_id: str,
    title: str,
    cwe: str | None = None,
    node: str | None = None,
    evidence: str | None = None,
    path: str | None = None,
    param: str | None = None,
    payload: str | None = None,
    oast_token: str | None = None,
) -> dict:
    """Report a discovered vulnerability. The engagement goal is to DISCOVER the
    arena's known weaknesses; this records your finding for scoring. Pass the
    `cwe` (e.g. 'CWE-89') and `node` so it can be credited.

    Supply the optional verification inputs so the finding can be PROVEN, not just
    claimed: `path` (a request path on the target), `param` + `payload` (the field
    and value that trigger it — e.g. an XSS/SQLi vector), and/or `oast_token` (an
    out-of-band callback token). The acknowledgement stays deliberately neutral —
    it won't tell you whether you were right, or whether verification passed."""
    _guard(ctx, "report_finding")
    trace_args = {"title": title[:256], "cwe": cwe, "node": node}
    try:
        res = ctx.client.report_finding(
            ctx.session.api_key, arena_id, title, cwe=cwe, node=node, evidence=evidence,
            path=path, param=param, payload=payload, oast_token=oast_token,
        )
    except Exception:
        _trace(ctx, "report_finding", trace_args, ok=False, arena_id=arena_id)
        raise
    _trace(ctx, "report_finding", trace_args, ok=True, arena_id=arena_id)
    return res


# --- defender stance ---------------------------------------------------------


def query_events(
    ctx: GatewayContext,
    arena_id: str,
    limit: int = 100,
    type: str | None = None,
) -> dict:
    """Read the arena's audit/event stream (newest first) — the defender's
    detection feed. Each entry is an audited action: deploy, status change, or
    `agent_exec` (a command the attacker ran, with node + exit code). Optionally
    filter by `type` (e.g. 'agent_exec'). Read-only."""
    _guard(ctx, "query_events")
    data = ctx.client.list_events(ctx.session.api_key, arena_id, limit)
    events = data.get("events", [])
    if type:
        events = [e for e in events if e.get("type") == type]
    _trace(ctx, "query_events", {"limit": limit, "type": type}, ok=True, arena_id=arena_id)
    return {"arena_id": arena_id, "count": len(events), "events": events}


def observe_traffic(ctx: GatewayContext, arena_id: str, seconds: int = 6,
                    max_packets: int = 200) -> dict:
    """MITM stance: observe in-flight traffic on the arena's shared segment for a
    bounded window — returns a flow summary (src/dst/proto/ports). In-path capture
    only (modify lands later). Orchestrator-gated to an mitm-bound session."""
    _guard(ctx, "observe_traffic")
    try:
        res = ctx.client.mitm_observe(ctx.session.api_key, arena_id, seconds, max_packets)
    except Exception:
        _trace(ctx, "observe_traffic", {"seconds": seconds}, ok=False, arena_id=arena_id)
        raise
    _trace(ctx, "observe_traffic",
           {"seconds": seconds, "packets": (res or {}).get("packets")},
           ok=True, arena_id=arena_id)
    return res


# --- configurator stance (SUT setup phase, ADR-0007 / P2-10) -----------------
# Bring an arbitrary OSS service up on the victim during a consented, time-boxed,
# victim-scoped setup session. The orchestrator enforces scope/budget/time-box;
# these tools are thin proxies + trace. NO attacker tools are exposed.


def get_setup_brief(ctx: GatewayContext, arena_id: str) -> dict:
    """What you need to bring the service up: the victim node(s) in scope, any
    white-box source mount path, the mode (hitl/autonomous), and remaining
    budget. Follow the project's own documented build/run steps."""
    _guard(ctx, "get_setup_brief")
    res = ctx.client.setup_brief(ctx.session.api_key, arena_id)
    _trace(ctx, "get_setup_brief", {}, ok=True, arena_id=arena_id)
    return res


def propose_setup_step(ctx: GatewayContext, arena_id: str, node: str, command: str,
                       rationale: str = "") -> dict:
    """HITL: propose a setup command on the victim node and return its `step_id`.
    It does NOT run until the operator approves — poll `await_setup_step`."""
    _guard(ctx, "propose_setup_step")
    try:
        res = ctx.client.setup_propose(ctx.session.api_key, arena_id, node, command, rationale)
    except Exception:
        _trace(ctx, "propose_setup_step",
               {"node": node, "command": command[:512]}, ok=False, arena_id=arena_id)
        raise
    _trace(ctx, "propose_setup_step",
           {"node": node, "command": command[:512], "step_id": res.get("step_id")},
           ok=True, arena_id=arena_id)
    return res


def await_setup_step(ctx: GatewayContext, arena_id: str, step_id: str) -> dict:
    """Poll a proposed step's outcome: pending | approved (with the exec result) |
    rejected. Call until it is no longer pending."""
    _guard(ctx, "await_setup_step")
    res = ctx.client.setup_proposal_status(ctx.session.api_key, arena_id, step_id)
    _trace(ctx, "await_setup_step",
           {"step_id": step_id, "status": res.get("status")}, ok=True, arena_id=arena_id)
    return res


def run_setup_step(ctx: GatewayContext, arena_id: str, node: str, command: str,
                   timeout: int = 60) -> dict:
    """Autonomous mode only (double-locked): run a setup command on the victim
    directly, no per-step approval. Returns its output."""
    _guard(ctx, "run_setup_step")
    _check_budget(ctx)
    try:
        res = ctx.client.setup_run(ctx.session.api_key, arena_id, node, command, timeout)
    except Exception:
        _trace(ctx, "run_setup_step",
               {"node": node, "command": command[:512]}, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1  # consume budget only on a step that actually ran
    _trace(ctx, "run_setup_step",
           {"node": node, "command": command[:512], "exit_code": res.get("exit_code")},
           ok=True, arena_id=arena_id)
    return res


def upload_file(ctx: GatewayContext, arena_id: str, node: str, path: str,
                content_b64: str) -> dict:
    """Write a file (base64) onto the victim node during setup — a config/seed/
    patch file. Victim-scoped + budgeted + audited like any setup step."""
    _guard(ctx, "upload_file")
    _check_budget(ctx)
    try:
        res = ctx.client.setup_upload(ctx.session.api_key, arena_id, node, path, content_b64)
    except Exception:
        _trace(ctx, "upload_file", {"node": node, "path": path}, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1  # consume budget only on a successful write
    _trace(ctx, "upload_file",
           {"node": node, "path": path, "bytes": res.get("bytes")}, ok=True, arena_id=arena_id)
    return res


def finish_setup(ctx: GatewayContext, arena_id: str) -> dict:
    """End the setup phase: revoke the configurator capability + setup egress
    before the engagement begins."""
    _guard(ctx, "finish_setup")
    res = ctx.client.setup_finish(ctx.session.api_key, arena_id)
    _trace(ctx, "finish_setup", {}, ok=True, arena_id=arena_id)
    return res
