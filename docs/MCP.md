# Agent Gateway (MCP)

The MCP gateway is the **only** path a bring-your-own agent has into an arena. It
exposes a small, stance-scoped tool set over the [Model Context Protocol](https://modelcontextprotocol.io),
authenticates the agent, enforces a server-side key↔arena binding, meters a budget,
and records every action to an append-only audit trace. Any MCP client works —
Claude Code, an Anthropic/OpenAI-compatible SDK loop, or your own framework.

Nidavellir ships no model of its own; the agent (and its key) are always yours.

## Connect an agent

An operator authorizes an agent, then points the agent's MCP client at the gateway.

1. **Create an agent key** (admin): `python auth.py create-key <name> agent`.
2. **Authorize it on the arena** (operator) — in the console's *Agent positioning*
   card, enter the key's **name**, pick a **stance**, and Authorize. This binds the
   name to the arena; the gateway rejects any tool call from an unbound key.
3. **Point the client at the gateway.** Two transports:

**Streamable HTTP** (recommended — no local files or paths):

```bash
claude mcp add --transport http nidavellir-arena http://localhost:9000/mcp
```

**stdio** (the gateway runs as a local subprocess) — a project `.mcp.json`:

```json
{
  "mcpServers": {
    "nidavellir-arena": {
      "command": "python", "args": ["-m", "gateway.server"],
      "env": {
        "PYTHONPATH": "/path/to/cyber-range/services/agent-gateway",
        "NIDAVELLIR_AGENT_KEY": "cg_…",
        "NIDAVELLIR_STANCE": "attacker",
        "NIDAVELLIR_API_URL": "http://127.0.0.1:8000",
        "NIDAVELLIR_GATEWAY_TRANSPORT": "stdio"
      }
    }
  }
}
```

The agent then works a specific arena by passing its `arena_id` (from the console)
to each tool call. On connect the gateway instructs the agent to `announce_agent`
first, orient with `get_briefing` / `get_topology`, then act.

## Stances & tools

A binding carries a **stance** that scopes which tools the agent may use. The
orchestrator re-checks the stance's capability on every call (defence in depth).

| Stance | Purpose | Stance tools |
|---|---|---|
| **attacker** | offensive testing from the foothold | `get_topology`, `list_targets`, `run_command`, `report_finding` |
| **defender** | detection over the event feed | `get_topology`, `query_events` |
| **mitm** | in-path traffic observation | `get_topology`, `observe_traffic` |
| **configurator** | bring a software-under-test up before the engagement | `get_setup_brief`, `propose_setup_step`, `await_setup_step`, `run_setup_step`, `upload_file`, `finish_setup` |
| **operator** | author scenarios with a connected model | `scaffold_scenario`, `import_scenario` |

Every stance also has the lifecycle tools: `announce_agent`, `get_briefing`,
`arena_status`, `list_scenarios`, `deploy_arena`, `destroy_arena`.

## Reporting a finding

`report_finding` records a discovered vulnerability. Pass `cwe` and `node` so it can
be scored; include a **`poc`** — a reproducible command, request, or steps a human
can run to verify — and, where available, the structured verification inputs
(`path`, `param`, `payload`, `oast_token`) so the platform can confirm it
deterministically. The acknowledgement is deliberately neutral: it never reveals
whether the finding matched the hidden manifest or whether verification passed, so an
agent-under-test cannot enumerate the ground truth. See
[`API.md`](./API.md) for the request shape and the operator verify/score endpoints.

## Guardrails

- **Key↔arena binding (server-enforced).** An agent key drives only the arenas it is
  bound to, and only within its stance's capabilities.
- **Kill-switch.** An operator can pause (freeze) or revoke a binding at any time;
  a paused agent's calls return `423 Locked`.
- **Budget.** A per-session step budget bounds a run (`NIDAVELLIR_STEP_BUDGET`).
- **Containment.** Arenas run on egress-locked networks; the foothold's only
  off-segment route is an allowlisted package mirror. See [`SECURITY.md`](./SECURITY.md).
- **Audit.** Every tool call is an append-only event and a JSONL trace, aligned to
  OpenTelemetry-GenAI / OpenInference for export (see [`INTERNALS.md`](./INTERNALS.md)).

## Configuration

The same image serves every transport; all settings come from the environment.

| Variable | Purpose | Default |
|---|---|---|
| `NIDAVELLIR_AGENT_KEY` | the agent principal's API key (secret) | — |
| `NIDAVELLIR_STANCE` | `attacker` / `defender` / `mitm` / `configurator` / `operator` | — |
| `NIDAVELLIR_API_URL` | orchestrator REST base URL | `http://127.0.0.1:8000` |
| `NIDAVELLIR_GATEWAY_TRANSPORT` | `stdio` / `streamable-http` / `sse` | `stdio` |
| `NIDAVELLIR_GATEWAY_HOST` / `_PORT` | bind address for HTTP transports | `127.0.0.1` / `9000` |
| `NIDAVELLIR_STEP_BUDGET` | per-session step cap (`0` = unbounded) | `0` |

Run it directly: `NIDAVELLIR_AGENT_KEY=cg_… python -m gateway.server` (stdio), or set
`NIDAVELLIR_GATEWAY_TRANSPORT=streamable-http` for the HTTP server on `:9000`. In the
Docker stack it is the opt-in `agent-gateway` profile.
