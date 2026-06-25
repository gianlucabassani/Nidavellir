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
    mcp = FastMCP("nidavellir-agent-gateway", host=cfg.host, port=cfg.port)

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
    def get_briefing(arena_id: str) -> dict:
        """The engagement brief + rules of engagement for the bound stance."""
        return tools.get_briefing(ctx(), arena_id=arena_id)

    @mcp.tool()
    def destroy_arena(arena_id: str) -> dict:
        """Tear down an arena."""
        return tools.destroy_arena(ctx(), arena_id=arena_id)

    @mcp.tool()
    def announce_agent(arena_id: str, model: str, provider: str) -> dict:
        """Declare the connected agent's model + provider so the operator console
        can show which AI is driving this arena. Telemetry only — the harness
        calls this, not the model."""
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
        def run_command(arena_id: str, command: str, node: str | None = None,
                        timeout: int = 30) -> dict:
            """Run a shell command from the arena foothold; returns its output."""
            return tools.run_command(
                ctx(), arena_id=arena_id, command=command, node=node, timeout=timeout
            )

        @mcp.tool()
        def report_finding(arena_id: str, title: str, cwe: str | None = None,
                           node: str | None = None, evidence: str | None = None) -> dict:
            """Report a discovered vulnerability (the engagement goal). Include
            the `cwe` (e.g. 'CWE-89') and `node` so it can be scored."""
            return tools.report_finding(
                ctx(), arena_id=arena_id, title=title, cwe=cwe, node=node, evidence=evidence
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

    elif stance is Stance.configurator:
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
