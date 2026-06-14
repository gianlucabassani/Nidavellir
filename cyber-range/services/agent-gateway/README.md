# CyberGuard Agent Gateway (MCP)

The **only** path a bring-your-own agent has into a running arena. An
[MCP](https://modelcontextprotocol.io) server (official Python SDK / `FastMCP`)
that exposes the arena **lifecycle** under `agent`-principal auth and a bound
**stance**, with an append-only audit trace. The per-stance execution toolsets
(attacker `run_command`, MITM intercept, defender detect) and their containment
guardrails land in a later, separately-reviewed increment — see
[ADR-0005](../../../docs/adr/0005-mcp-agent-gateway.md).

This service is **not an AI.** The agent (model + key) is the user's; the
gateway is the integration surface (scope boundary in `VISION.md`).

## Tools (this skeleton)

| Tool | Proxies | Notes |
|------|---------|-------|
| `list_scenarios()` | `GET /scenarios` | scenarios this key may deploy |
| `deploy_arena(scenario, provider?)` | `POST /deploy` | returns the canonical `arena_id` |
| `arena_status(arena_id)` | `GET /status/{id}` | poll until `active`; includes outputs |
| `get_briefing(arena_id)` | status + registry | stance, scenario, rules of engagement |
| `destroy_arena(arena_id)` | `DELETE /destroy/{id}` | always available |

## Run

```bash
pip install -r requirements.txt

# stdio (local dev — one agent/stance per process)
CYBERGUARD_API_URL=http://localhost:8000 \
CYBERGUARD_AGENT_KEY=cg_...               \
CYBERGUARD_STANCE=attacker                \
python -m gateway.server

# streamable HTTP
CYBERGUARD_GATEWAY_TRANSPORT=streamable-http \
CYBERGUARD_GATEWAY_HOST=0.0.0.0 CYBERGUARD_GATEWAY_PORT=9000 \
CYBERGUARD_AGENT_KEY=cg_... python -m gateway.server
```

| Env var | Default | Meaning |
|---------|---------|---------|
| `CYBERGUARD_API_URL` | `http://localhost:8000` | orchestrator REST base URL |
| `CYBERGUARD_AGENT_KEY` | — (required) | the agent principal's API key (secret) |
| `CYBERGUARD_STANCE` | unbound | `attacker` \| `mitm` \| `defender` |
| `CYBERGUARD_GATEWAY_TRANSPORT` | `stdio` | `stdio` \| `streamable-http` \| `sse` |
| `CYBERGUARD_GATEWAY_HOST` / `_PORT` | `127.0.0.1` / `9000` | HTTP bind |
| `CYBERGUARD_TRACE_DIR` | unset (off) | dir for `<arena_id>.jsonl` traces |

## Layout

```
gateway/
  config.py       # env-driven config
  stances.py      # Stance enum + per-stance tool allow-lists
  session.py      # authenticated principal + bound stance (derived agent_id)
  rest_client.py  # thin HTTP client over the orchestrator REST API
  tools.py        # lifecycle tool logic (pure; unit-tested) + GatewayContext
  trace.py        # append-only JSONL trace (never logs the raw key)
  server.py       # FastMCP wiring + transport (`python -m gateway.server`)
```

The package is namespaced (`gateway.*`) so it does not collide with the
orchestrator's flat modules; it talks to the orchestrator only over REST.
