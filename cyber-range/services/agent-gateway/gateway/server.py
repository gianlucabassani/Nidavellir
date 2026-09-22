"""
The MCP server: registers the shared lifecycle tools and wires the transport.

Built on the official MCP Python SDK (`FastMCP`). The tool wrappers are thin —
each delegates to `gateway.tools`, which holds the testable logic. Beyond the
shared lifecycle surface, the per-stance execution toolsets are registered here
according to the bound stance (attacker: recon + `run_command` +
`report_finding`; defender: `query_events`) and gated by `stances.allowed_tools`.

Run:
    NIDAVELLIR_AGENT_KEY=cg_... python -m gateway.server                # stdio
    NIDAVELLIR_GATEWAY_TRANSPORT=streamable-http python -m gateway.server
"""
import logging

from mcp.server.fastmcp import FastMCP

from gateway import tools
from gateway.config import GatewayConfig
from gateway.rest_client import RestClient
from gateway.session import session_from_config
from gateway.stances import Stance, parse_stance
from gateway.tools import GatewayContext

logger = logging.getLogger(__name__)


def build_context(cfg: GatewayConfig | None = None) -> GatewayContext:
    cfg = cfg or GatewayConfig()
    return GatewayContext(
        client=RestClient(cfg.api_url, timeout=cfg.rest_timeout),
        session=session_from_config(cfg),
        trace_dir=cfg.trace_dir,
        step_budget=cfg.step_budget,
    )


def build_server(cfg: GatewayConfig | None = None, context: GatewayContext | None = None) -> FastMCP:
    """Construct the FastMCP server with the lifecycle tools registered.

    The session/context is resolved lazily on first tool call (so the server
    builds even before an agent key is set — handy for introspection/tests).
    """
    cfg = cfg or GatewayConfig()
    mcp = FastMCP(
        "nidavellir-agent-gateway", host=cfg.host, port=cfg.port,
        instructions=(
            "You are a bring-your-own security agent connected to a contained "
            "Nidavellir cyber-range arena over MCP. Do this in order:\n"
            "1. FIRST call announce_agent(arena_id, model, provider) once, before "
            "anything else, so the operator console shows which agent is driving "
            "the arena.\n"
            "2. Call get_briefing and get_topology to orient (objective, targets, "
            "rules of engagement).\n"
            "3. Work the target with the stance's tools (e.g. run_command from the "
            "foothold).\n"
            "4. For every vulnerability you confirm, call report_finding — pass "
            "the structured verification inputs (path, param, payload, oast_token) "
            "when you have them, and ALWAYS include a `poc`: a short, reproducible "
            "proof a human can run to verify it (a curl/HTTP request, a shell "
            "command, or numbered steps, with the observed result)."
        ),
    )

    holder = {"ctx": context}

    def ctx() -> GatewayContext:
        if holder["ctx"] is None:
            holder["ctx"] = build_context(cfg)
        return holder["ctx"]

    @mcp.tool()
    def list_scenarios() -> dict:
        """List the scenarios this agent key is allowed to deploy."""
        return tools.list_scenarios(ctx())

    @mcp.tool()
    def deploy_arena(scenario: str, provider: str | None = None) -> dict:
        """Deploy a scenario as a new arena. Returns its arena_id."""
        return tools.deploy_arena(ctx(), scenario=scenario, provider=provider)

    @mcp.tool()
    def arena_status(arena_id: str) -> dict:
        """Get an arena's status and outputs (poll until status is 'active')."""
        return tools.arena_status(ctx(), arena_id=arena_id)

    @mcp.tool()
    def session_preflight(arena_id: str) -> dict:
        """Verify the immutable target identity, authorization, infrastructure,
        workspace and reset contract before research begins."""
        return tools.session_preflight(ctx(), arena_id=arena_id)

    @mcp.tool()
    def get_briefing(arena_id: str) -> dict:
        """The engagement brief + rules of engagement for the bound stance."""
        return tools.get_briefing(ctx(), arena_id=arena_id)

    @mcp.tool()
    def destroy_arena(arena_id: str) -> dict:
        """Tear down an arena."""
        return tools.destroy_arena(ctx(), arena_id=arena_id)

    @mcp.tool()
    def announce_agent(arena_id: str, model: str, provider: str) -> dict:
        """Call this FIRST, once, before any other tool. Declare who you are —
        your model (e.g. "opus", "gpt-4o") and provider (e.g. "anthropic",
        "openai") — so the operator console registers this session and shows
        which agent is driving the arena. Safe to call again to update the
        declaration."""
        return tools.announce_agent(ctx(), arena_id=arena_id, model=model, provider=provider)

    # Per-stance tools: only register what the bound stance may use, so an
    # agent's tool list reflects its stance (the runtime guard re-checks).
    stance = parse_stance(cfg.stance)

    if stance is Stance.attacker:
        @mcp.tool()
        def get_topology(arena_id: str) -> dict:
            """The arena's nodes (IPs, URLs, which is the foothold) and networks."""
            return tools.get_topology(ctx(), arena_id=arena_id)

        @mcp.tool()
        def list_targets(arena_id: str) -> dict:
            """The in-scope targets (non-foothold nodes) and how to reach them."""
            return tools.list_targets(ctx(), arena_id=arena_id)

        @mcp.tool()
        def workspace_status(arena_id: str) -> dict:
            """List source workspaces this attacker may inspect. Only targets
            explicitly configured for white-box access are returned."""
            return tools.workspace_status(ctx(), arena_id=arena_id)

        @mcp.tool()
        def workspace_diff(
            arena_id: str,
            node: str,
            base: str = "HEAD",
            path: str | None = None,
            context_lines: int = 3,
            start_line: int = 0,
            max_lines: int = 300,
        ) -> dict:
            """Inspect a bounded Git diff page for a white-box target workspace.
            Use next_start_line to continue large diffs."""
            return tools.workspace_diff(
                ctx(), arena_id=arena_id, node=node, base=base, path=path,
                context_lines=context_lines, start_line=start_line,
                max_lines=max_lines,
            )

        @mcp.tool()
        def workspace_patch_artifact(
            arena_id: str, node: str, base: str = "HEAD",
            path: str | None = None, context_lines: int = 3,
            include_untracked_paths: list[str] | None = None,
        ) -> dict:
            """Export a SHA-256 patch artifact. Untracked content is included
            only for explicitly selected regular UTF-8 files."""
            return tools.workspace_patch_artifact(
                ctx(), arena_id=arena_id, node=node, base=base, path=path,
                context_lines=context_lines,
                include_untracked_paths=include_untracked_paths,
            )

        @mcp.tool()
        def run_command(arena_id: str, command: str, node: str | None = None,
                        timeout: int = 30) -> dict:
            """Run a shell command from the arena foothold; returns its output."""
            return tools.run_command(
                ctx(), arena_id=arena_id, command=command, node=node, timeout=timeout
            )

        @mcp.tool()
        def submit_poc(
            arena_id: str, source: str, target_node: str | None = None,
            transfer_files: list[str] | None = None, timeout_seconds: int = 30,
            memory_mb: int = 128, cpu_millis: int = 500, pids: int = 32,
            idempotency_key: str | None = None,
        ) -> dict:
            """Run Python in a disposable networkless helper. For target HTTP,
            import nidavellir and call nidavellir.request(relative_path)."""
            return tools.submit_poc(
                ctx(), arena_id, source, target_node, transfer_files,
                timeout_seconds, memory_mb, cpu_millis, pids, idempotency_key,
            )

        @mcp.tool()
        def poc_status(arena_id: str, job_id: str) -> dict:
            """Read confined PoC state and cleanup status without output bodies."""
            return tools.poc_status(ctx(), arena_id, job_id)

        @mcp.tool()
        def poc_result(arena_id: str, job_id: str) -> dict:
            """Read bounded stdout/stderr, digests and artifacts for a terminal PoC."""
            return tools.poc_result(ctx(), arena_id, job_id)

        @mcp.tool()
        def cancel_poc(arena_id: str, job_id: str) -> dict:
            """Request cancellation and helper reclamation for a PoC job."""
            return tools.cancel_poc(ctx(), arena_id, job_id)

        @mcp.tool()
        def browser_visit(
            arena_id: str, node: str, path: str = "/",
            params: dict[str, str] | None = None, wait_ms: int = 1500,
        ) -> dict:
            """Render a page with JavaScript on an arena target. Supply a node
            and relative path/query params; arbitrary URLs are not accepted."""
            return tools.browser_visit(
                ctx(), arena_id=arena_id, node=node, path=path,
                params=params, wait_ms=wait_ms,
            )

        @mcp.tool()
        def http_request(
            arena_id: str, node: str, path: str = "/",
            params: dict[str, str] | None = None, method: str = "GET",
            headers: dict[str, str] | None = None, body: str | None = None,
        ) -> dict:
            """Perform ONE HTTP transaction against an arena target's web
            service. Supply a node and relative path; arbitrary URLs are not
            accepted. Returns the bounded response with its whole-body SHA-256;
            redirects are reported as metadata, never followed."""
            return tools.http_request(
                ctx(), arena_id=arena_id, node=node, path=path,
                params=params, method=method, headers=headers, body=body,
            )

        @mcp.tool()
        def list_http_transactions(
            arena_id: str, limit: int | None = None, offset: int = 0,
        ) -> dict:
            """List this arena's stored HTTP transactions, newest first. Each
            has a `digest` usable with get_http_transaction /
            replay_http_transaction."""
            return tools.list_http_transactions(
                ctx(), arena_id=arena_id, limit=limit, offset=offset
            )

        @mcp.tool()
        def get_http_transaction(arena_id: str, digest: str) -> dict:
            """Fetch one stored HTTP transaction by digest: the manifest plus
            the full request/response envelope."""
            return tools.get_http_transaction(ctx(), arena_id=arena_id, digest=digest)

        @mcp.tool()
        def replay_http_transaction(
            arena_id: str, digest: str, node: str | None = None,
            path: str | None = None, params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None, method: str | None = None,
            body: str | None = None,
        ) -> dict:
            """Re-send a stored transaction with edits. params/headers merge
            onto the stored ones; node/path/method/body replace when given.
            The original stays immutable; the new record links to it via
            replay_of."""
            return tools.replay_http_transaction(
                ctx(), arena_id=arena_id, digest=digest, node=node,
                path=path, params=params, headers=headers, method=method,
                body=body,
            )

        @mcp.tool()
        def upload_file(
            arena_id: str, path: str, content_b64: str, node: str | None = None
        ) -> dict:
            """Upload a bounded base64 payload below the foothold's fixed
            /opt/nidavellir-transfer root. `path` must be relative."""
            return tools.upload_file(
                ctx(), arena_id=arena_id, path=path,
                content_b64=content_b64, node=node,
            )

        @mcp.tool()
        def download_file(
            arena_id: str, path: str, node: str | None = None,
            offset: int = 0, max_bytes: int = 262144,
        ) -> dict:
            """Download a regular foothold file chunk as base64. Follow
            next_offset until null; verify the returned whole-file SHA-256."""
            return tools.download_file(
                ctx(), arena_id=arena_id, path=path, node=node,
                offset=offset, max_bytes=max_bytes,
            )

        @mcp.tool()
        def report_finding(arena_id: str, title: str, cwe: str | None = None,
                           node: str | None = None, evidence: str | None = None,
                           path: str | None = None, param: str | None = None,
                           payload: str | None = None, oast_token: str | None = None,
                           poc: str | None = None,
                           evidence_artifact_digests: list[str] | None = None,
                           transaction_digests: list[str] | None = None) -> dict:
            """Report a discovered vulnerability (the engagement goal). Include the
            `cwe` (e.g. 'CWE-89') and `node` so it can be scored. To have the finding
            PROVEN (not just claimed), also pass the verification inputs: `path` +
            `param` + `payload` for a reflected-XSS / SQLi vector, or `oast_token`
            for an out-of-band callback. Always include a `poc` — a short,
            reproducible proof a human can run to verify it (a curl/HTTP request, a
            shell command, or numbered steps, with the observed result)."""
            return tools.report_finding(
                ctx(), arena_id=arena_id, title=title, cwe=cwe, node=node,
                evidence=evidence, path=path, param=param, payload=payload,
                oast_token=oast_token, poc=poc,
                evidence_artifact_digests=evidence_artifact_digests,
                transaction_digests=transaction_digests,
            )

    elif stance is Stance.defender:
        @mcp.tool()
        def get_topology(arena_id: str) -> dict:
            """The arena's nodes (IPs, URLs, foothold) and networks — what to watch."""
            return tools.get_topology(ctx(), arena_id=arena_id)

        @mcp.tool()
        def query_events(arena_id: str, limit: int = 100, type: str | None = None) -> dict:
            """Read the arena's audit/event stream (the detection feed). Filter by
            `type` (e.g. 'agent_exec' for attacker commands)."""
            return tools.query_events(ctx(), arena_id=arena_id, limit=limit, type=type)

    elif stance is Stance.mitm:
        @mcp.tool()
        def get_topology(arena_id: str) -> dict:
            """The arena's nodes (IPs, networks) — the segment you're in-path on."""
            return tools.get_topology(ctx(), arena_id=arena_id)

        @mcp.tool()
        def observe_traffic(arena_id: str, seconds: int = 6, max_packets: int = 200) -> dict:
            """Observe in-flight traffic on the arena's shared segment for a bounded
            window; returns a flow summary (src/dst/proto/ports). In-path capture."""
            return tools.observe_traffic(ctx(), arena_id=arena_id, seconds=seconds, max_packets=max_packets)

    elif stance is Stance.configurator:
        @mcp.tool()
        def workspace_status(arena_id: str) -> dict:
            """List writable SUT source workspaces available during setup."""
            return tools.workspace_status(ctx(), arena_id=arena_id)

        @mcp.tool()
        def workspace_diff(
            arena_id: str,
            node: str,
            base: str = "HEAD",
            path: str | None = None,
            context_lines: int = 3,
            start_line: int = 0,
            max_lines: int = 300,
        ) -> dict:
            """Inspect a bounded Git diff page for setup changes. Use
            next_start_line to continue large diffs."""
            return tools.workspace_diff(
                ctx(), arena_id=arena_id, node=node, base=base, path=path,
                context_lines=context_lines, start_line=start_line,
                max_lines=max_lines,
            )

        @mcp.tool()
        def workspace_patch_artifact(
            arena_id: str, node: str, base: str = "HEAD",
            path: str | None = None, context_lines: int = 3,
            include_untracked_paths: list[str] | None = None,
        ) -> dict:
            """Export a SHA-256 setup-workspace patch artifact."""
            return tools.workspace_patch_artifact(
                ctx(), arena_id=arena_id, node=node, base=base, path=path,
                context_lines=context_lines,
                include_untracked_paths=include_untracked_paths,
            )

        @mcp.tool()
        def get_setup_brief(arena_id: str) -> dict:
            """What you need to bring the service up: victim node(s) in scope, any
            white-box source path, the mode, and remaining budget."""
            return tools.get_setup_brief(ctx(), arena_id=arena_id)

        @mcp.tool()
        def propose_setup_step(arena_id: str, node: str, command: str,
                               rationale: str = "") -> dict:
            """HITL: propose a setup command on the victim; returns a step_id. It
            runs only after the operator approves — poll await_setup_step."""
            return tools.propose_setup_step(
                ctx(), arena_id=arena_id, node=node, command=command, rationale=rationale
            )

        @mcp.tool()
        def await_setup_step(arena_id: str, step_id: str) -> dict:
            """Poll a proposed step: pending | approved (with result) | rejected."""
            return tools.await_setup_step(ctx(), arena_id=arena_id, step_id=step_id)

        @mcp.tool()
        def run_setup_step(arena_id: str, node: str, command: str, timeout: int = 60) -> dict:
            """Autonomous only (double-locked): run a setup command on the victim
            directly, no per-step approval."""
            return tools.run_setup_step(
                ctx(), arena_id=arena_id, node=node, command=command, timeout=timeout
            )

        @mcp.tool()
        def upload_file(arena_id: str, node: str, path: str, content_b64: str) -> dict:
            """Write a base64 file onto the victim during setup (config/seed/patch)."""
            return tools.upload_file(
                ctx(), arena_id=arena_id, node=node, path=path, content_b64=content_b64
            )

        @mcp.tool()
        def finish_setup(arena_id: str) -> dict:
            """End setup: revoke the configurator capability + egress before the
            engagement."""
            return tools.finish_setup(ctx(), arena_id=arena_id)

    elif stance is Stance.operator:
        @mcp.tool()
        def scaffold_scenario(prompt: str, provider_class: str | None = None) -> dict:
            """Generate a candidate v3 scenario from a natural-language prompt using
            your connected model. Returns {valid, spec, topology, errors,
            suggested_id} for REVIEW — it does NOT deploy or save. provider_class
            optionally pins the backend ('container' | 'vm' | 'any')."""
            return tools.scaffold_scenario(ctx(), prompt=prompt, provider_class=provider_class)

        @mcp.tool()
        def import_scenario(spec: dict, id: str | None = None, overwrite: bool = False) -> dict:
            """Persist a reviewed v3 spec as a reusable pack (use after
            scaffold_scenario). Returns the registered scenario id."""
            return tools.import_scenario(ctx(), spec=spec, scenario_id=id, overwrite=overwrite)

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = GatewayConfig()
    logger.info("Starting Nidavellir agent gateway (transport=%s, api=%s)", cfg.transport, cfg.api_url)
    build_server(cfg).run(transport=cfg.transport)


if __name__ == "__main__":
    main()
