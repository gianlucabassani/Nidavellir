"""Gateway configuration, resolved from the environment."""
import os

DEFAULT_API_URL = "http://localhost:8000"


class GatewayConfig:
    """Runtime configuration for the MCP gateway process.

    All values come from the environment so the same image serves stdio (dev)
    and streamable-HTTP (prod). The agent's API key is a *secret* — it is read
    here and forwarded to the orchestrator; it is never logged or traced raw.
    """

    def __init__(self, env: dict | None = None):
        env = env if env is not None else os.environ
        # Upstream orchestrator REST API.
        self.api_url = env.get("CYBERGUARD_API_URL", DEFAULT_API_URL).rstrip("/")
        # The agent principal's API key (forwarded to the orchestrator).
        self.agent_key = env.get("CYBERGUARD_AGENT_KEY")
        # The session's stance (attacker | mitm | defender), or unbound.
        self.stance = env.get("CYBERGUARD_STANCE")
        # MCP transport: "stdio" (dev) | "streamable-http" (prod) | "sse".
        self.transport = env.get("CYBERGUARD_GATEWAY_TRANSPORT", "stdio")
        # Bind address for HTTP transports. 127.0.0.1 by default — a deployment
        # opens it deliberately via compose/ALB, never implicitly.
        self.host = env.get("CYBERGUARD_GATEWAY_HOST", "127.0.0.1")
        self.port = int(env.get("CYBERGUARD_GATEWAY_PORT", "9000"))
        self.rest_timeout = float(env.get("CYBERGUARD_REST_TIMEOUT", "15"))
        # Where per-arena JSONL traces are written; unset → no file trace.
        self.trace_dir = env.get("CYBERGUARD_TRACE_DIR") or None
