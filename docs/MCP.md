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
| **attacker** | offensive testing from the foothold | `get_topology`, `list_targets`, `run_command`, `submit_poc`, `poc_status`, `poc_result`, `cancel_poc`, `browser_visit`, `http_request`, `list_http_transactions`, `get_http_transaction`, `replay_http_transaction`, `upload_file`, `download_file`, `workspace_status`, `workspace_diff`, `workspace_patch_artifact`, `report_finding` |
| **defender** | detection over the event feed | `get_topology`, `query_events` |
| **mitm** | in-path traffic observation | `get_topology`, `observe_traffic` |
| **configurator** | bring a software-under-test up before the engagement | `get_setup_brief`, `workspace_status`, `workspace_diff`, `workspace_patch_artifact`, `propose_setup_step`, `await_setup_step`, `run_setup_step`, `upload_file`, `finish_setup` |
| **operator** | author scenarios with a connected model | `scaffold_scenario`, `import_scenario` |

Every stance also has the lifecycle tools: `announce_agent`, `get_briefing`,
`arena_status`, `session_preflight`, `list_scenarios`, `deploy_arena`,
`destroy_arena`.

`session_preflight(arena_id)` should be called before research begins. It returns
the immutable target identity, authorization basis, reset contract, readiness
checks, and the next valid phase. Required checks fail closed in the orchestrator;
MCP does not merely provide an advisory duplicate.

### Workspace changes

`workspace_status(arena_id)` lists only source workspaces authorized for the
binding: an attacker receives explicitly declared white-box source mounted
as a writable research copy on its foothold, separate from the running target;
a configurator receives the writable SUT checkout.
`workspace_diff(arena_id, node, base="HEAD", path=null, context_lines=3,
start_line=0, max_lines=300)` returns changed-file status and one bounded diff
page. Follow `next_start_line` for large patches. Untracked names are reported,
but their content is not read until tracked, preventing an untrusted symlink from
turning the viewer into an arbitrary-file reader.
`workspace_patch_artifact(...)` exports the complete bounded view as a SHA-256
artifact and returns the exact patch plus its digest. Pass explicitly selected
regular UTF-8 paths in `include_untracked_paths` when their contents are needed.
The digest can then be supplied to `report_finding` through
`evidence_artifact_digests`, binding reproducible source evidence to the finding.
The same field accepts HTTP transaction digests via `transaction_digests` —
the digests returned by `http_request` / `replay_http_transaction`.

### File transfer

`upload_file(arena_id, path, content_b64, node=null)` places a payload below the
foothold's fixed `/opt/nidavellir-transfer` root. `download_file(...)` retrieves a
regular file in bounded base64 chunks; follow `next_offset` and verify the stable
whole-file `digest`. Neither tool accepts an absolute/traversing path, neither can
target a victim directly, and trace/event records omit file bodies.

### Headless browser

`browser_visit(arena_id, node, path="/", params={}, wait_ms=1500)` renders a
JavaScript-heavy target and returns bounded DOM plus its SHA-256. It is charged
against the session step budget and traced without query values or response body.
There is deliberately no URL argument: the orchestrator resolves an in-scope,
non-foothold arena node and the provider attaches disposable Chromium only to that
node's arena segment. This is also the execution oracle used when `report_finding`
validates reflected XSS.

### HTTP research primitive

`http_request(arena_id, node, path="/", params={}, method="GET", headers={},
body=None)` performs ONE HTTP transaction against an arena target's web service
in a disposable arena-bound runner. Like `browser_visit`, there is no URL
argument; redirects are reported as `redirect_location` metadata and never
followed. The response carries bounded content plus its whole-body SHA-256, and
every call persists a content-addressed transaction record:
`list_http_transactions(arena_id)` (newest first), `get_http_transaction(
arena_id, digest)` (full request/response envelope), and
`replay_http_transaction(arena_id, digest, ...)` re-send a stored transaction
with edits — `params`/`headers` merge onto the stored values,
`node`/`path`/`method`/`body` replace when given — producing a new linked
record (`replay_of`) while the original stays immutable. All four are
budget-charged and traced with parameter/header NAMES and digests only, never
bodies or values; the server applies the identical scope checks as the REST
route.

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
