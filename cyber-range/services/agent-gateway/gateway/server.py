"""
The MCP server: registers the shared lifecycle tools and wires the transport.

Built on the official MCP Python SDK (`FastMCP`). The tool wrappers are thin —
each delegates to `gateway.tools`, which holds the testable logic. Per-stance
execution toolsets (and their guardrails) are added in a later increment; this
skeleton exposes only the lifecycle surface.

Run:
    CYBERGUARD_AGENT_KEY=cg_... python -m gateway.server                # stdio
    CYBERGUARD_GATEWAY_TRANSPORT=streamable-http python -m gateway.server
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
    mcp = FastMCP("cyberguard-agent-gateway", host=cfg.host, port=cfg.port)

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

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = GatewayConfig()
    logger.info("Starting CyberGuard agent gateway (transport=%s, api=%s)", cfg.transport, cfg.api_url)
    build_server(cfg).run(transport=cfg.transport)


if __name__ == "__main__":
    main()
