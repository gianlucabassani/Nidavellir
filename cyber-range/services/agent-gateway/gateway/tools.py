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
from gateway.stances import Stance

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
    """Legacy process-local warning; the orchestrator owns durable admission."""
    if ctx.step_budget and ctx.steps_used >= ctx.step_budget:
        raise BudgetExceeded(
            f"command/step budget ({ctx.step_budget}) exhausted for this session"
        )


def budget_status(ctx: GatewayContext, arena_id: str) -> dict:
    _guard(ctx, "budget_status")
    result = ctx.client.budget_status(ctx.session.api_key, arena_id)
    _trace(ctx, "budget_status", {}, ok=True, arena_id=arena_id)
    return result


def stop_arena(ctx: GatewayContext, arena_id: str, reason: str) -> dict:
    _guard(ctx, "stop_arena")
    result = ctx.client.stop_arena(ctx.session.api_key, arena_id, reason)
    _trace(ctx, "stop_arena", {"reason": reason}, ok=True, arena_id=arena_id)
    return result


def resume_arena(ctx: GatewayContext, arena_id: str, reason: str) -> dict:
    _guard(ctx, "resume_arena")
    result = ctx.client.resume_arena(ctx.session.api_key, arena_id, reason)
    _trace(ctx, "resume_arena", {"reason": reason}, ok=True, arena_id=arena_id)
    return result


def emergency_stop(ctx: GatewayContext, reason: str) -> dict:
    _guard(ctx, "emergency_stop")
    result = ctx.client.emergency_stop(ctx.session.api_key, reason)
    _trace(ctx, "emergency_stop", {"reason": reason}, ok=True)
    return result


def clear_emergency_stop(ctx: GatewayContext, reason: str) -> dict:
    _guard(ctx, "clear_emergency_stop")
    result = ctx.client.clear_emergency_stop(ctx.session.api_key, reason)
    _trace(ctx, "clear_emergency_stop", {"reason": reason}, ok=True)
    return result


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


def session_preflight(ctx: GatewayContext, arena_id: str) -> dict:
    """Get immutable target identity, reset contract and readiness checks."""
    _guard(ctx, "session_preflight")
    try:
        result = ctx.client.session_preflight(ctx.session.api_key, arena_id)
    except Exception:
        _trace(ctx, "session_preflight", {}, ok=False, arena_id=arena_id)
        raise
    _trace(
        ctx,
        "session_preflight",
        {
            "status": (result or {}).get("status"),
            "ready": bool((result or {}).get("ready")),
            "failed_checks": (result or {}).get("failed_checks", []),
        },
        ok=True,
        arena_id=arena_id,
    )
    return result


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


def workspace_status(ctx: GatewayContext, arena_id: str) -> dict:
    """List source workspaces visible to this stance.

    The orchestrator is authoritative: an attacker receives only explicit
    white-box source, while a configurator receives the writable setup checkout.
    """
    _guard(ctx, "workspace_status")
    try:
        result = ctx.client.list_workspaces(ctx.session.api_key, arena_id)
    except Exception:
        _trace(ctx, "workspace_status", {}, ok=False, arena_id=arena_id)
        raise
    _trace(
        ctx,
        "workspace_status",
        {"workspace_count": len((result or {}).get("workspaces", []))},
        ok=True,
        arena_id=arena_id,
    )
    return result


def workspace_diff(
    ctx: GatewayContext,
    arena_id: str,
    node: str,
    *,
    base: str = "HEAD",
    path: str | None = None,
    context_lines: int = 3,
    start_line: int = 0,
    max_lines: int = 300,
) -> dict:
    """Read a bounded Git diff page from a stance-authorized workspace."""
    _guard(ctx, "workspace_diff")
    args = {
        "node": node,
        "base": base,
        "path": path,
        "context_lines": context_lines,
        "start_line": start_line,
        "max_lines": max_lines,
    }
    try:
        result = ctx.client.workspace_diff(
            ctx.session.api_key,
            arena_id,
            node,
            base=base,
            path=path,
            context_lines=context_lines,
            start_line=start_line,
            max_lines=max_lines,
        )
    except Exception:
        _trace(ctx, "workspace_diff", args, ok=False, arena_id=arena_id)
        raise
    _trace(
        ctx,
        "workspace_diff",
        {
            **args,
            "changed_file_count": (result or {}).get("changed_file_count", 0),
            "returned_lines": (result or {}).get("returned_lines", 0),
        },
        ok=True,
        arena_id=arena_id,
    )
    return result


def workspace_patch_artifact(
    ctx: GatewayContext,
    arena_id: str,
    node: str,
    *,
    base: str = "HEAD",
    path: str | None = None,
    context_lines: int = 3,
    include_untracked_paths: list[str] | None = None,
) -> dict:
    """Create a hashed patch artifact from a stance-authorized workspace."""
    _guard(ctx, "workspace_patch_artifact")
    args = {
        "node": node, "base": base, "path": path,
        "context_lines": context_lines,
        "include_untracked_paths": include_untracked_paths or [],
    }
    try:
        result = ctx.client.workspace_patch_artifact(
            ctx.session.api_key, arena_id, node, base=base, path=path,
            context_lines=context_lines,
            include_untracked_paths=include_untracked_paths,
        )
    except Exception:
        _trace(ctx, "workspace_patch_artifact", args, ok=False, arena_id=arena_id)
        raise
    artifact = (result or {}).get("artifact") or {}
    _trace(
        ctx, "workspace_patch_artifact",
        {"node": node, "digest": artifact.get("digest"), "bytes": artifact.get("bytes")},
        ok=True, arena_id=arena_id,
    )
    return result


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


def browser_visit(
    ctx: GatewayContext,
    arena_id: str,
    node: str,
    path: str = "/",
    params: dict[str, str] | None = None,
    wait_ms: int = 1500,
) -> dict:
    """Render JavaScript on one in-scope arena target (never an arbitrary URL)."""
    _guard(ctx, "browser_visit")
    _check_budget(ctx)
    args = {
        "node": node, "path": path, "param_names": sorted((params or {}).keys()),
        "wait_ms": wait_ms,
    }
    try:
        result = ctx.client.browser_visit(
            ctx.session.api_key, arena_id, node, path, params, wait_ms
        )
    except Exception:
        _trace(ctx, "browser_visit", args, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1
    _trace(
        ctx, "browser_visit",
        {**args, "dom_sha256": (result or {}).get("dom_sha256")},
        ok=True, arena_id=arena_id,
    )
    return result


def http_request(
    ctx: GatewayContext,
    arena_id: str,
    node: str,
    path: str = "/",
    params: dict[str, str] | None = None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> dict:
    """Perform ONE HTTP transaction against an arena target's web service
    (never an arbitrary URL). Scope checks are server-side; traces and the
    audit event carry names and digests only — never bodies or values."""
    _guard(ctx, "http_request")
    _check_budget(ctx)
    args = {
        "node": node, "method": method.upper(), "path": path,
        "param_names": sorted((params or {}).keys()),
        "header_names": sorted((headers or {}).keys()),
        "has_body": body is not None,
    }
    try:
        result = ctx.client.http_request(
            ctx.session.api_key, arena_id, node, path, params, method,
            headers, body,
        )
    except Exception:
        _trace(ctx, "http_request", args, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1
    _trace(
        ctx, "http_request",
        {**args,
         "status": (result or {}).get("status"),
         "transaction_digest": (result or {}).get("transaction_digest")},
        ok=True, arena_id=arena_id,
    )
    return result


def list_http_transactions(
    ctx: GatewayContext, arena_id: str,
    limit: int | None = None, offset: int = 0,
) -> dict:
    """List the arena's stored HTTP transactions, newest first."""
    _guard(ctx, "list_http_transactions")
    _check_budget(ctx)
    args = {"limit": limit, "offset": offset}
    try:
        result = ctx.client.http_transactions(
            ctx.session.api_key, arena_id, limit, offset
        )
    except Exception:
        _trace(ctx, "list_http_transactions", args, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1
    _trace(
        ctx, "list_http_transactions",
        {**args, "total": (result or {}).get("total")},
        ok=True, arena_id=arena_id,
    )
    return result


def get_http_transaction(ctx: GatewayContext, arena_id: str, digest: str) -> dict:
    """Fetch one stored HTTP transaction envelope by digest."""
    _guard(ctx, "get_http_transaction")
    _check_budget(ctx)
    try:
        result = ctx.client.http_transaction(ctx.session.api_key, arena_id, digest)
    except Exception:
        _trace(ctx, "get_http_transaction", {"digest": digest}, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1
    _trace(ctx, "get_http_transaction", {"digest": digest}, ok=True, arena_id=arena_id)
    return result


def replay_http_transaction(
    ctx: GatewayContext,
    arena_id: str,
    digest: str,
    *,
    node: str | None = None,
    path: str | None = None,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
    body: str | None = None,
) -> dict:
    """Re-send a stored HTTP transaction with optional edits; the new record
    links to the original via `replay_of`. Same server-side scope checks as a
    direct request."""
    _guard(ctx, "replay_http_transaction")
    _check_budget(ctx)
    args = {
        "digest": digest, "node": node, "path": path, "method": method,
        "param_names": sorted((params or {}).keys()) if params else [],
        "header_names": sorted((headers or {}).keys()) if headers else [],
        "has_body": body is not None,
    }
    try:
        result = ctx.client.http_replay(
            ctx.session.api_key, arena_id, digest, node=node, path=path,
            params=params, headers=headers, method=method, body=body,
        )
    except Exception:
        _trace(ctx, "replay_http_transaction", args, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1
    _trace(
        ctx, "replay_http_transaction",
        {**args,
         "status": (result or {}).get("status"),
         "transaction_digest": (result or {}).get("transaction_digest")},
        ok=True, arena_id=arena_id,
    )
    return result


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
    poc: str | None = None,
    evidence_artifact_digests: list[str] | None = None,
    transaction_digests: list[str] | None = None,
) -> dict:
    """Report a discovered vulnerability. The engagement goal is to DISCOVER the
    arena's known weaknesses; this records your finding for scoring. Pass the
    `cwe` (e.g. 'CWE-89') and `node` so it can be credited.

    Supply the optional verification inputs so the finding can be PROVEN, not just
    claimed: `path` (a request path on the target), `param` + `payload` (the field
    and value that trigger it — e.g. an XSS/SQLi vector), and/or `oast_token` (an
    out-of-band callback token). Always include a `poc`: a short, reproducible
    proof a human can run to verify it — a `curl`/HTTP request, a shell command,
    or numbered steps (include the observed result). Bind stored HTTP traffic as
    evidence with `transaction_digests` (digests from http_request /
    replay_http_transaction). The acknowledgement stays deliberately neutral — it
    won't tell you whether you were right, or whether verification passed."""
    _guard(ctx, "report_finding")
    trace_args = {"title": title[:256], "cwe": cwe, "node": node}
    try:
        res = ctx.client.report_finding(
            ctx.session.api_key, arena_id, title, cwe=cwe, node=node, evidence=evidence,
            path=path, param=param, payload=payload, oast_token=oast_token, poc=poc,
            evidence_artifact_digests=evidence_artifact_digests,
            transaction_digests=transaction_digests,
        )
    except Exception:
        _trace(ctx, "report_finding", trace_args, ok=False, arena_id=arena_id)
        raise
    _trace(ctx, "report_finding", trace_args, ok=True, arena_id=arena_id)
    return res


def submit_poc(
    ctx: GatewayContext, arena_id: str, source: str, target_node: str | None = None,
    transfer_files: list[str] | None = None, timeout_seconds: int = 30,
    memory_mb: int = 128, cpu_millis: int = 500, pids: int = 32,
    idempotency_key: str | None = None,
) -> dict:
    """Submit Python to the worker-owned networkless runner.

    Target access, when selected, is only through ``nidavellir.request`` inside
    the PoC. Source and file bodies are deliberately omitted from the trace.
    """
    _guard(ctx, "submit_poc")
    _check_budget(ctx)
    key = idempotency_key or f"mcp-{uuid.uuid4().hex}"
    meta = {
        "target_node": target_node, "transfer_files": transfer_files or [],
        "timeout_seconds": timeout_seconds, "source_bytes": len(source.encode("utf-8")),
    }
    try:
        result = ctx.client.submit_poc(
            ctx.session.api_key, arena_id, source, target_node=target_node,
            transfer_files=transfer_files, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb, cpu_millis=cpu_millis, pids=pids,
            idempotency_key=key,
        )
    except Exception:
        _trace(ctx, "submit_poc", meta, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1
    meta["job_id"] = ((result or {}).get("job") or {}).get("id")
    _trace(ctx, "submit_poc", meta, ok=True, arena_id=arena_id)
    return result


def poc_status(ctx: GatewayContext, arena_id: str, job_id: str) -> dict:
    _guard(ctx, "poc_status")
    result = ctx.client.poc_job(ctx.session.api_key, arena_id, job_id)
    job = (result or {}).get("job") or {}
    # Status intentionally excludes stdout/stderr/artifact bodies.
    job = {key: value for key, value in job.items() if key != "result"}
    _trace(ctx, "poc_status", {"job_id": job_id, "state": job.get("state")},
           ok=True, arena_id=arena_id)
    return {"job": job}


def poc_result(ctx: GatewayContext, arena_id: str, job_id: str) -> dict:
    _guard(ctx, "poc_result")
    result = ctx.client.poc_job(ctx.session.api_key, arena_id, job_id)
    job = (result or {}).get("job") or {}
    _trace(ctx, "poc_result", {
        "job_id": job_id, "state": job.get("state"),
        "input_digest": job.get("input_digest"),
    }, ok=True, arena_id=arena_id)
    return result


def cancel_poc(ctx: GatewayContext, arena_id: str, job_id: str) -> dict:
    _guard(ctx, "cancel_poc")
    result = ctx.client.cancel_poc(ctx.session.api_key, arena_id, job_id)
    _trace(ctx, "cancel_poc", {"job_id": job_id}, ok=True, arena_id=arena_id)
    return result


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


def upload_file(ctx: GatewayContext, arena_id: str, node: str | None, path: str,
                content_b64: str) -> dict:
    """Upload a bounded base64 file.

    Attackers write below the foothold's fixed transfer root. Configurators keep
    the setup-specific victim upload path, which is separately budgeted.
    """
    _guard(ctx, "upload_file")
    _check_budget(ctx)
    try:
        if ctx.session.stance is Stance.configurator:
            if not node:
                raise ValueError("configurator upload requires a victim node")
            res = ctx.client.setup_upload(
                ctx.session.api_key, arena_id, node, path, content_b64
            )
        else:
            res = ctx.client.transfer_upload(
                ctx.session.api_key, arena_id, path, content_b64, node=node
            )
    except Exception:
        _trace(ctx, "upload_file", {"node": node, "path": path}, ok=False, arena_id=arena_id)
        raise
    ctx.steps_used += 1  # consume budget only on a successful write
    _trace(ctx, "upload_file",
           {"node": node, "path": path, "bytes": res.get("bytes")}, ok=True, arena_id=arena_id)
    return res


def download_file(
    ctx: GatewayContext, arena_id: str, path: str, node: str | None = None,
    offset: int = 0, max_bytes: int = 262144,
) -> dict:
    """Download one bounded foothold file chunk as base64 with an exact digest."""
    _guard(ctx, "download_file")
    try:
        res = ctx.client.transfer_download(
            ctx.session.api_key, arena_id, path, node=node,
            offset=offset, max_bytes=max_bytes,
        )
    except Exception:
        _trace(
            ctx, "download_file", {"node": node, "path": path, "offset": offset},
            ok=False, arena_id=arena_id,
        )
        raise
    _trace(
        ctx, "download_file",
        {
            "node": res.get("node"), "path": path, "offset": offset,
            "returned_bytes": res.get("returned_bytes"), "digest": res.get("digest"),
        },
        ok=True, arena_id=arena_id,
    )
    return res


def finish_setup(ctx: GatewayContext, arena_id: str) -> dict:
    """End the setup phase: revoke the configurator capability + setup egress
    before the engagement begins."""
    _guard(ctx, "finish_setup")
    res = ctx.client.setup_finish(ctx.session.api_key, arena_id)
    _trace(ctx, "finish_setup", {}, ok=True, arena_id=arena_id)
    return res
