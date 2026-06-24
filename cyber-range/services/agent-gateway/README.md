# Nidavellir Agent Gateway (MCP)

The **only** path a bring-your-own agent has into a running arena. An
[MCP](https://modelcontextprotocol.io) server (official Python SDK / `FastMCP`)
that exposes the arena **lifecycle** under `agent`-principal auth and a bound
**stance**, with an append-only audit trace. The per-stance execution toolsets
(attacker `run_command`/`report_finding`, defender `query_events`, configurator
SUT-setup) are implemented and gated by the bound stance; MITM intercept is the
next increment — see [ADR-0005](../../../docs/adr/0005-mcp-agent-gateway.md) and
the stance tables below.

This service is **not an AI.** The agent (model + key) is the user's; the
gateway is the integration surface (scope boundary in `VISION.md`).

## Tools

**Lifecycle** (every session):

| Tool | Proxies | Notes |
|------|---------|-------|
| `list_scenarios()` | `GET /scenarios` | scenarios this key may deploy |
| `deploy_arena(scenario, provider?)` | `POST /deploy` | returns the canonical `arena_id` |
| `arena_status(arena_id)` | `GET /status/{id}` | poll until `active`; includes outputs |
| `get_briefing(arena_id)` | status + registry | stance, scenario, rules of engagement |
| `destroy_arena(arena_id)` | `DELETE /destroy/{id}` | always available |
| `announce_agent(arena_id, model, provider)` | `POST /arenas/{id}/agent-session` | declares the connected model/provider (+ bound stance) for the console's *connected model* chip; harness plumbing, telemetry only |

**Attacker stance** (`NIDAVELLIR_STANCE=attacker`):

| Tool | Backend | Notes |
|------|---------|-------|
| `get_topology(arena_id)` | `GET /status` | nodes (IP/URL/state) + networks; marks the foothold |
| `list_targets(arena_id)` | `GET /status` | in-scope targets (non-foothold nodes) + how to reach them |
| `run_command(arena_id, command, node?, timeout?)` | `POST /arenas/{id}/exec` | shell on the **foothold only**; budget-charged; audited + traced |
| `report_finding(arena_id, title, cwe?, node?, evidence?)` | `POST /arenas/{id}/findings` | report a discovered vulnerability; scored by CWE+node vs the hidden manifest; neutral ack (no oracle) |

**Defender stance** (`NIDAVELLIR_STANCE=defender`):

| Tool | Backend | Notes |
|------|---------|-------|
| `get_topology(arena_id)` | `GET /status` | what to watch |
| `query_events(arena_id, limit?, type?)` | `GET /deployments/{id}/events` | the audit/detection feed; filter by type (e.g. `agent_exec`) |

**Configurator stance** (`NIDAVELLIR_STANCE=configurator`) — SUT setup, gated (ADR-0007). Time-boxed, **victim-scoped**, write-capable, revoked before the engagement. **No attacker tools.** The orchestrator enforces consent/scope/time-box/budget; an open setup session (started by the operator with a `mode`) must exist.

| Tool | Backend | Notes |
|------|---------|-------|
| `get_setup_brief(arena_id)` | `GET /arenas/{id}/setup/brief` | victim node(s) in scope, white-box source path, mode, budget |
| `propose_setup_step(arena_id, node, command, rationale?)` | `POST .../setup/propose` | **HITL**: propose a step → operator must approve before it runs |
| `await_setup_step(arena_id, step_id)` | `GET .../setup/proposals/{id}` | poll a proposal: pending \| approved (+result) \| rejected |
| `run_setup_step(arena_id, node, command, timeout?)` | `POST .../setup/run` | **autonomous** only — double-locked (platform flag + `mode=autonomous`) |
| `upload_file(arena_id, node, path, content_b64)` | `POST .../setup/upload` | write a config/seed/patch file on the victim (gated exec) |
| `finish_setup(arena_id)` | `POST .../setup/finish` | revoke the configurator capability + setup egress before the engagement |

The MITM toolset is the next increment (see the resume plan in `.agent/STATE.md`).

## Reference client

A thin bring-your-own Claude agent that drives this gateway over MCP lives in
[`examples/agent-harness/`](../../../examples/agent-harness/) — a wiring sample
(BYO `ANTHROPIC_API_KEY`), not a product. It connects over streamable HTTP,
lists the stance's tools, and runs an engagement end-to-end (deploy → recon →
`run_command` → `report_finding` → destroy).

## Run

```bash
pip install -r requirements.txt

# stdio (local dev — one agent/stance per process)
NIDAVELLIR_API_URL=http://localhost:8000 \
NIDAVELLIR_AGENT_KEY=cg_...               \
NIDAVELLIR_STANCE=attacker                \
python -m gateway.server

# streamable HTTP
NIDAVELLIR_GATEWAY_TRANSPORT=streamable-http \
NIDAVELLIR_GATEWAY_HOST=0.0.0.0 NIDAVELLIR_GATEWAY_PORT=9000 \
NIDAVELLIR_AGENT_KEY=cg_... python -m gateway.server
```

| Env var | Default | Meaning |
|---------|---------|---------|
| `NIDAVELLIR_API_URL` | `http://localhost:8000` | orchestrator REST base URL |
| `NIDAVELLIR_AGENT_KEY` | — (required) | the agent principal's API key (secret) |
| `NIDAVELLIR_STANCE` | unbound | `attacker` \| `defender` \| `configurator` \| `mitm` |
| `NIDAVELLIR_GATEWAY_TRANSPORT` | `stdio` | `stdio` \| `streamable-http` \| `sse` |
| `NIDAVELLIR_GATEWAY_HOST` / `_PORT` | `127.0.0.1` / `9000` | HTTP bind |
| `NIDAVELLIR_TRACE_DIR` | unset (off) | dir for `<arena_id>.jsonl` traces |

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
