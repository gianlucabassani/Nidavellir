# API Reference

Base URL: `http://localhost:8000`

## Durable research budgets and stop controls

New arenas receive a versioned aggregate action cap (default 1000, configured
with `ARENA_ACTION_BUDGET`) and an absolute deadline no later than deployment
expiry. `GET /arenas/{id}/budget` returns cap, spent, reserved, remaining,
deadline and arena/system stop state. A bound agent can read its arena's
allowance; operator keys can read any arena. Archived records remain readable.

Research writes reserve one action in the orchestrator before execution. An
optional `X-Action-Key` (8–128 safe characters) binds a caller retry to the
same request digest and actor. The response includes `X-Action-ID`; key reuse
with other input is rejected. Rejected requests release reservations; ambiguous
server errors retain a charge. Status, results, audit reads, cancellation and
stop controls remain available after exhaustion. The gateway's local step
counter is only a secondary warning; reconnect never replenishes the server
account. PoC jobs hold the reservation until completion; a queued cancellation
releases it, and an interrupted execution retains a charge. A reset replacement
inherits the source allowance.

Operators can `POST /arenas/{id}/budget/policy` with `action_cap`, ISO
`deadline` and `reason`, `POST /arenas/{id}/stop` or `/resume` with `reason`
and an `idempotency_key`.
Admins can `GET` or `POST /system/emergency-stop`, and `POST
/system/emergency-stop/clear`; those writes require the same key. Stop reports
`stopping` until in-flight actions
and helpers drain, then `stopped`; re-arm requires explicit cleanup verification.
The current console exposes arena stop in the workspace and system stop under
Settings. Operator MCP tools expose the same stop controls; all stances can
read their bound arena budget.

Token and cost caps are unavailable for external BYO agents because the
orchestrator cannot reserve trusted pre-execution model usage. Requests with
`token_budget` or `cost_budget_usd` at engagement creation, token/cost headers
on research actions, or token/cost fields in a policy revision are refused.

## Runtime capabilities and scoped TCP forwards

`GET /arenas/{id}/capabilities` returns `nidavellir.runtime-capabilities.v1`
for the authenticated principal. Agent keys must be bound to the arena. Each
operation has a `ready`, `supported`, `unavailable`, or `unsupported` state, a
stable reason, recording status and bounded limits. The response includes
visible target/foothold names, only forward service IDs reachable from that
foothold, durable budget remaining/deadline, and arena/system stop state. It
never contains scenario truth, private source paths, binding lists or secrets.
`token_cost_hard_cap` is `unsupported` for external agents.

A versioned scenario node may declare an internal TCP service separately from
host-published `ports[]`:

```json
{"name":"fixture","role":"victim","image":"sha256:...",
 "segments":["research"],"ports":[],
 "forward_services":[{"id":"internal","port":8123}]}
```

For Docker-local, an operator or an agent with an active **attacker** binding
may `POST /arenas/{id}/forwards` with `foothold`, `target`, `service_id`,
`lifetime_seconds` (10–300), and an 8–128 character `idempotency_key`.
The foothold and target must share a declared internal segment. Arbitrary
addresses, ports, URLs, SOCKS, UDP and egress-open arenas are refused. One
atomic budget action pays for creation; retrying the same key and input returns
the same lease without a second charge. `GET /arenas/{id}/forwards` and
`GET /arenas/{id}/forwards/{forward_id}` report owner-visible state, expiry,
byte counts and cleanup; `POST .../{forward_id}/revoke` is idempotent.

The binary stream is `ws(s)://API/arenas/{id}/forwards/{forward_id}/connect`.
Send `X-API-Key` in the WebSocket **header**, never in its URL. The server
reauthenticates the owner/binding, claims the single stream and spends a second
action. A worker starts one labeled trusted relay on the selected internal
segment, connected only to the resolved target IP and declared port. Each
direction is capped at 1 MiB; the stream is capped at 90 seconds and 15 idle
seconds. Revocation, binding pause/revoke, stop, expiry, reset and teardown
close it. A destroyed arena retains the lease and body-free audit metadata.
The local client binds only loopback:

```bash
export NIDAVELLIR_API_KEY='your operator or bound attacker key'
python3 scripts/nv-forward-client.py --arena ARENA_ID --forward FORWARD_ID \
  --listen-port 18080 --api-url http://127.0.0.1:8000
```

The client requires the pinned `websockets` dependency. The current Flask
workspace shows the manifest and provides CSRF-protected lease create/revoke
forms. MCP exposes `runtime_capabilities` to every bound stance and
`open_forward`, `forward_status`, `revoke_forward` to attacker sessions; binary
bytes remain in the authenticated WebSocket client.

## Confined PoC execution

Docker-local arenas support `POST /arenas/{id}/poc-jobs` (202),
`GET /arenas/{id}/poc-jobs`, `GET /arenas/{id}/poc-jobs/{job_id}`, and
`POST /arenas/{id}/poc-jobs/{job_id}/cancel`. Submission requires an active
arena and `CAP_EXEC`; agents must have a live attacker binding and can read or
cancel only their own jobs. Results remain available to authorized readers after
arena destruction. Cross-arena job IDs are rejected.

Example body:

```json
{
  "source": "import nidavellir\nprint(nidavellir.request('/health')['status'])\n",
  "target_node": "web",
  "transfer_files": [],
  "timeout_seconds": 10,
  "memory_mb": 64,
  "cpu_millis": 250,
  "pids": 16,
  "idempotency_key": "health-proof-001"
}
```

Use `target_node: null` for fully networkless work. The fixed HTTP(S) relay accepts
relative paths, optional method/headers/body, and returns a dictionary with status,
headers and a bytes body. It never follows redirects. Direct TCP/UDP, arbitrary
URLs, caller images and runtime package installation are unsupported.

Selected files come from the arena transfer area and are copied to
`/workspace/input/<path>`; no host or foothold volume is mounted. Source is capped
at 64 KiB, transfer input at eight files / 1 MiB, stdout and stderr at 64 KiB each,
and artifacts at eight regular files / 1 MiB by default. Write artifacts under
`/workspace/artifacts`. Traversal, links and special-file artifacts are refused.

Responses wrap a `job` with input digest, resolved target policy, resource limits,
deadline, state, cleanup state and timestamps. Detail adds bounded output,
artifact content/digests and the actual runner image identity. A repeated key
reuses the original job only when principal, input, target, image and limits match.
Capacity and conflicting idempotency requests return 409. Cancellation is durable;
poll until terminal and inspect `cleanup_state` separately. A lost worker's job
fails without replay, and the reaper reconciles its labelled resources.

HTTP/browser routes retain their synchronous response shape but execute on the
worker using durable jobs. The console's PoC workspace and attacker MCP tools
`submit_poc`, `poc_status`, `poc_result`, `cancel_poc` use these same contracts.



## Overview

The Nidavellir API provides RESTful endpoints for managing arena deployments.
 All operations are **asynchronous**.

### Authentication

All endpoints except `GET /health` require an API key in the `X-API-Key`
header (see [ADR-0002](adr/0002-api-authentication.md)):

```bash
export NIDAVELLIR_API_KEY=cg_...   # create one: python auth.py create-key <name> <role>
curl -H "X-API-Key: $NIDAVELLIR_API_KEY" http://localhost:8000/deployments
```

Roles: `admin` (manage platform/keys), `operator` (author/run/observe
engagements), `agent` (the AI under test). Recorded for auditing; per-owner
enforcement is future hosted-product work. Missing or invalid keys
get `401`. The docker-compose stack bootstraps the key from the
`NIDAVELLIR_API_KEY` value in `.env` — the default `dev-insecure-key` is for
the local mock demo only.

> The role set is `admin` / `operator` / `agent` (the legacy
> `instructor`/`student` were renamed to `operator` in the 2026-06 pivot; keys
> issued with the old roles still authenticate). `attacker`/`MITM`/`defender`
> are per-session agent **stances** (chosen via the MCP gateway), not auth roles.

> All examples below assume `-H "X-API-Key: $NIDAVELLIR_API_KEY"` is added.

### Workspace change intelligence

For an active source-backed arena:

- `GET /arenas/{id}/workspaces` lists provider-discovered Git workspaces visible
  to the caller. Operators and unrestricted personal sandboxes get the applicable
  workspace; configurators get writable SUT source; attackers get only source
  explicitly declared `whitebox`.
- `GET /arenas/{id}/workspaces/{node}/diff` returns status plus a clean bounded
  diff. Query parameters: `base` (`HEAD`, a HEAD ancestor, or 7–40 hex commit),
  optional relative `path`, `context_lines` (0–20), `start_line`, and `max_lines`
  (1–500). Continue at `next_start_line`.
- `POST /arenas/{id}/workspaces/{node}/patch-artifacts` collects that same
  paginated view into a bounded, arena-scoped SHA-256 patch artifact. Body fields:
  `base`, optional `path`, `context_lines`, and up to ten
  `include_untracked_paths`. Untracked content is opened only after explicit
  selection and only when the provider proves it is a bounded regular UTF-8 file.
  The response carries the artifact metadata and exact patch body.
- `GET /arenas/{id}/evidence-artifacts/{sha256:digest}` downloads the verified
  patch after re-checking the caller's arena binding and workspace visibility.

The caller never supplies a repository location: it is resolved from deployment
outputs. Git hooks, pagers, external diff drivers and textconv are disabled.
Changed files are grouped as staged, unstaged, and untracked. Diff and artifact
events retain metadata/digests only; source and exploit material remain in the
bounded evidence store, never in the append-only event log.

### Foothold file transfer

- `POST /arenas/{id}/files/upload` accepts `{path, content_b64, node?}` and writes
  one bounded file below `/opt/nidavellir-transfer` on an arena foothold.
- `POST /arenas/{id}/files/download` accepts
  `{path, node?, offset=0, max_bytes}` and returns a base64 chunk, whole-file
  SHA-256, byte counts, and `next_offset` for continuation.

Paths are relative, traversal is rejected, and attacker bindings are restricted
to foothold nodes server-side. Docker transfer uses archive APIs instead of a
shell; downloads reject links and non-regular files. Default limits are 1 MiB per
file and 256 KiB per returned chunk. Audit events contain path, size, offsets and
digest—never file contents.

### Arena-scoped headless browser

`POST /arenas/{id}/browser/visit` accepts
`{node, path="/", params={}, wait_ms=1500}` and returns bounded rendered DOM,
title, full-DOM SHA-256 and truncation metadata. It never accepts a URL: the API
resolves the target from that arena's outputs, rejects footholds, and the Docker
provider repeats IP ownership before attaching disposable Chromium to the target's
arena segment. The runner is time/resource bounded, capability-dropped,
no-new-privileges and read-only. Audit events retain metadata and digest—not query
values or rendered content.

The same primitive is the authoritative `reflected_xss` validator. It injects a
platform-owned nonce payload and confirms CWE-79 only when JavaScript writes that
nonce into the rendered DOM. Reflection without execution is not credited.

### Arena-target HTTP research primitive (R1)

`POST /arenas/{id}/http/request` accepts
`{node, path="/", params={}, method="GET", headers={}, body=null}` and performs
ONE HTTP transaction against that arena node's web service in a disposable,
arena-network-bound curl runner. It never accepts a URL: the API resolves the
target from the arena's outputs (unknown node → 404, foothold → 403, no web
port → 422), and the provider re-verifies IP ownership before starting the
runner (capability-dropped, no-new-privileges, read-only, CPU/RAM/PID/time
bounded). Redirects are never followed — they are returned as
`redirect_location` metadata so the primitive cannot be walked off-target.
Request bodies are text-only and capped (`HTTP_MAX_REQUEST_BYTES`, 256 KiB);
framing headers (`Content-Length`, `Transfer-Encoding`) are dropped. The
response returns bounded content (`HTTP_MAX_RESPONSE_BYTES`, 1 MiB) with the
whole-body SHA-256 even when truncated. `success` reports transport failure
only — any observed status (including 5xx) is a successful transaction.
Audit events carry metadata and digests only: parameter/header NAMES,
`has_body`, `status`, `body_bytes`, `body_sha256` — never bodies or query
values. Distinct from MITM `capture_traffic`, which observes packet flow.

Every successful transaction is also persisted content-addressed (R1 slice 3):
the canonical request+response envelope is stored under the arena's namespace,
digest-keyed (`transaction_digest` in the response and audit event). Identical
byte-for-byte re-sends dedup onto one record; any change — including a replay —
produces a new record. Records are bounded per-envelope and store-wide, are
readable after the arena is destroyed, and are served by:

- `GET /arenas/{id}/http/transactions?limit=&offset=` — newest-first manifests;
- `GET /arenas/{id}/http/transactions/{digest}` — the full envelope
  (request and response, bodies included), integrity-verified on read.
Both require the same `exec` binding as driving; a destroyed arena's records
stay reviewable.

`POST /arenas/{id}/http/transactions/{digest}/replay` re-sends a stored
transaction (R1 slice 4). Overrides are optional: `params`/`headers` MERGE
onto the stored values, while `node`, `path`, `method`, and `body` REPLACE
when provided. The stored record is never mutated — every replay produces a
new content-addressed transaction whose manifest links to its parent via
`replay_of` (surfaced in the response and audit event too). Replays require
the arena to be active and carry the same binding/scope/rate-limit checks as
a direct drive; unknown digests are 404, malformed ones 422.

Findings accept `transaction_digests` alongside `evidence_artifact_digests`
(R1 slice 6): each digest is verified against this arena's transaction store
at submission time and recorded on the finding as a reference — method, path,
node, status, byte size, and replay linkage. The agent's MCP
`report_finding` accepts the same field.

### Health Check

`GET /health` — unauthenticated liveness probe, returns `{"status": "ok"}`.
Used by the container healthcheck.

### Input validation

Deploy requests are validated before anything is queued (`422` on failure):

- `instance_id` (friendly name): `^[a-z0-9][a-z0-9-]{0,39}$` — lowercase
  letters, digits, hyphens; max 40 chars.
- `scenario`: must match `^[a-z0-9][a-z0-9_-]{0,63}$` **and** exist in the
  registry (`GET /scenarios`). Names that look like paths are rejected here
  and again inside the worker (defense in depth).
- `engagement_purpose` is optional for compatibility clients. When present on
  any deployment request it must be `benchmark`, `discovery`, `calibration`, or
  `research`. The orchestrator records it once as an append-only
  `engagement_intent` event with challenge/target source; it does not override
  scenario, provider, containment, or scoring policy.
- `participant_mode` is optional immutable intent: `operator`, `agent`, or
  `mixed`. It does not grant agent access; arena bindings and stance capabilities
  remain authoritative.
- `engagement_time_box_seconds` is an optional enforced runtime limit from 300
  through 86400 seconds. When supplied, it sets the deployment expiry used by
  the reaper; otherwise the installation-wide TTL remains in force.

### Scenario Registry

`GET /scenarios` — the deployable scenarios with display metadata. Clients
should drive their scenario pickers from this (the WebUI does):

```json
{
  "scenarios": [
    {
      "id": "basic_pentest",
      "name": "Web App Pentest (VM)",
      "title": "Web App Pentest (VM)",
      "description": "…",
      "difficulty": "medium",
      "tags": [],
      "provider_class": "vm",
      "nodes": 3,
      "valid": true
    }
  ]
}
```

`provider_class` (`vm` | `container`) is the infrastructure class the scenario
needs — it must match the `infra_class` of the provider that deploys it (see
below). `nodes` is the topology size and `valid` is `true` when the scenario
validates against the [v3 schema](scenario.schema.json) (see
[SCENARIOS.md](SCENARIOS.md)); a `false` here means the registry fell back to
raw metadata for a non-conforming template.

**Authoring & import (operator-only).** `POST /scenarios` validates a v3 spec
(JSON object or YAML/JSON string) and persists it as a reusable pack;
`DELETE /scenarios/{id}` removes an imported pack (built-ins are read-only);
`POST /scenarios/preview` dry-runs a candidate (a pasted spec or catalog `picks`)
returning `{valid, errors, warnings, topology}` without deploying;
`GET /scenarios/{id}/topology` returns a registered pack's topology graph.

`POST /scenarios/import/vulhub` (operator-only) converts a [Vulhub](https://github.com/vulhub/vulhub)
Docker Compose environment into a v3 pack — deterministically, no model in the
loop. Provide `path` (a Vulhub env dir, e.g. `weblogic/CVE-2017-10271`, fetched
from GitHub at `ref`, default `master`) **or** `compose` (a pasted compose object
or YAML string, for offline use). Each compose service → one `victim` node; a
build-only service maps to a gated `service.source` (needs
`NIDAVELLIR_ALLOW_SOURCE_BUILD`); a Kali foothold is added unless
`include_attacker: false`. Lossy conversions (dropped `volumes`/`depends_on`/…)
are returned in `warnings`. `dry_run: true` previews (validate + topology) without
saving; otherwise the pack is persisted and appears in `GET /scenarios`. VulnHub
(full VM disks) is a separate, planned track. Returns `422` on an unconvertible
compose, `409` on an id collision (pass `overwrite: true`).

**Generate from a prompt (operator-only, BYO model — P3).** `POST /scenarios/generate`
turns a natural-language `prompt` into a candidate v3 spec using the **operator's
own connected model** (the model bubble; decrypted in-process, never logged).
Optional `provider_class` (`container` | `vm` | `any`) pins the backend class.
The model is called in **JSON mode** (OpenAI-compatible providers incl. Gemini get
`response_format: json_object`; Anthropic is prefilled with `{`) so the reply is
valid JSON by construction. It validates the generated spec and returns
`{valid, errors, warnings, suggested_id, summary, topology, spec}` **without
deploying or saving** — the review gate (P3-2): the operator reviews the spec +
topology, then imports it via `POST /scenarios` and launches. `409` when no model
is connected; a model reply that isn't usable JSON returns `valid: false` with the
model's `raw` reply (and provider errors are surfaced cleanly), never a `500`.
Scope boundary: Nidavellir supplies the prompt + validation + review gate, never
the AI — the model and key are the operator's, and generation is operator-only
(it is **not** exposed to in-arena agent stances).

### Provider Registry

`GET /providers` — the deployment backends available in this install and the
infrastructure class each one provides:

```json
{
  "providers": [
    { "name": "aws", "infra_class": "vm" },
    { "name": "docker-local", "infra_class": "container" },
    { "name": "mock", "infra_class": "any" },
    { "name": "openstack", "infra_class": "vm" }
  ]
}
```

A provider with `infra_class: any` (mock) accepts every scenario; otherwise
the scenario's `provider_class` must equal the provider's `infra_class` or
the deploy is rejected with `422`.

### Image catalog & custom arenas (manual scenario creator)

`GET /catalog` — the curated attacker/victim images an operator can pick to
build a custom arena (optional `?kind=attacker|victim`):

```json
{
  "images": [
    {"id": "kali-cli", "name": "Kali Linux (CLI)", "kind": "attacker",
     "image": "kalilinux/kali-rolling:latest", "provider_class": "container",
     "access": "cli", "available": true, "ports": []},
    {"id": "dvwa", "name": "DVWA", "kind": "victim", "access": "web",
     "ports": [80], "available": true}
  ]
}
```

`POST /arenas/custom` — build a custom arena from catalog picks. The topology is
compiled server-side from the whitelist (no arbitrary image strings), validated
against the v3 schema, and queued as an inline scenario — it never touches the
scenario registry. Container-class, so it defaults to the `docker-local`
provider.

```json
{ "instance_id": "my-lab", "attacker": "kali-cli", "victims": ["dvwa"],
  "provider": "docker-local" }
```

Returns `{"status": "accepted", "instance_id": "<system-uuid>"}`. A bad
selection (unknown id, wrong kind, a VM-only image like `mr-robot`) is rejected
with `422`. Images are pulled on first launch; a target that exits immediately
is surfaced as `node_<name>_state: "exited"` + `unhealthy_nodes` in the arena
status, not a silent success.

### In-arena command execution

`POST /arenas/{instance_id}/exec` — run a command inside an arena node and get
its output. This is the backend the MCP gateway's attacker-stance `run_command`
tool proxies. Synchronous; provider-enforced (`docker exec`, SSH for VM
providers once wired). **Every exec is written to the `events` audit trail.**

```json
{ "node": "jump", "command": "nmap -sV 10.0.0.2", "timeout": 30 }
→ { "node": "jump", "exit_code": 0, "stdout": "...", "stderr": "" }
```

`POST /arenas/{instance_id}/mitm/observe` `{seconds?, max_packets?}` — the MCP
**MITM** stance's `observe_traffic` backend: capture in-flight traffic on the
arena's shared segment bridge for a bounded window and return a flow summary
(`{flows:[{src,dst,proto,sport,dport}], packets, bridge}`). docker-local taps the
segment's bridge device via a short-lived host-net tcpdump sidecar (privileged by
nature). D1: an `agent` key needs an **`mitm`** binding (CAP_OBSERVE); operators
bypass. `501` on a provider without capture, `409` if the arena isn't active.
Audited as `mitm_observe`. (In-path `modify` is a later increment.)

**Authorization (D1):** an `agent`-role key may exec only on an arena it is
**bound** to (see *Agent ↔ arena bindings* below) — `403` otherwise. Foothold
node-scope is now **enforced server-side** for an `attacker`-stance binding (not
just at the gateway): an attacker may exec only on a foothold node, `403` on a
victim. Operators/admins bypass (they manage every arena).

`403` unbound agent / out-of-stance node · `404` unknown arena/node · `409` arena
not `active` · `501` provider has no exec (VM providers, for now) · `422` empty
command or out-of-range timeout (1–120s). Output is capped; the command is
bounded to 4096 chars.

### Connected-agent telemetry

`POST /arenas/{instance_id}/agent-session` — a bring-your-own agent declares the
**model + provider** driving an arena. This is the backend the MCP gateway's
`announce_agent` tool proxies; the model/provider are self-declared (Nidavellir
ships no AI), recorded as an append-only `agent_session` event, and surfaced as
the operator console's *connected model* chip. Attribution/telemetry only — not
ground truth, not scored.

```json
{ "model": "gemini-2.0-flash", "provider": "gemini", "stance": "attacker" }
→ { "recorded": true }
```

`404` unknown arena · `422` missing `model`/`provider`. Any authenticated
principal may call it (the agent announces itself). The latest `agent_session`
event (via `GET /events`) drives the console chip.

### Agent ↔ arena bindings (server-enforced, D1)

The orchestrator — not just the gateway — decides whether an `agent` key may
**drive** an arena (exec / report findings / configure, observe, or destroy the
arena), and in what stance. Without a binding an agent key cannot touch an arena it has no
relationship to (the gateway's stance gate was client-side only). State is
event-backed (`agent_binding` / `agent_binding_revoked` — no migration).

A binding is created three ways:
- **auto on self-deploy** — when an `agent` key deploys an arena (`/deploy`,
  `/arenas/custom`) it is auto-bound with an unrestricted (`stance: null`)
  binding — its own sandbox;
- **operator grant** — `POST /arenas/{id}/bindings` (below);
- **named at `setup/start`** — `agent_name` grants a `configurator` binding for
  the session, revoked at `setup/finish` (the write/config capability is dropped
  before the engagement).

A binding's **stance** scopes what it permits (server-side): `null` →
unrestricted within the arena; `attacker` → exec (foothold-only) + findings;
`configurator` → setup steps; `mitm` → traffic observation; `defender` → reads
only. Every active stance may destroy its bound arena through the shared
lifecycle tool. Operators/admins are never bound and bypass every check.

- `POST /arenas/{id}/bindings` `{ "agent_name": "redteam", "stance": "attacker" }`
  → `{ "bound": true, … }`. Operator-only. Re-granting updates the stance.
- `GET /arenas/{id}/bindings` → `{ "bindings": [ … ] }` (active bindings; each
  carries a `paused` flag). Operator-only.
- `DELETE /arenas/{id}/bindings/{agent_name}` → `{ "revoked": true|false }`.
  Operator-only; idempotent. This is the **kill** — the binding is torn down.

**Kill-switch / pause (P2-11).** A reversible halt distinct from a kill — the
binding stays in place but its driving actions are frozen:
- `POST /arenas/{id}/bindings/{agent_name}/pause` → `{ "paused": true, … }`.
  Operator-only, idempotent. While paused, the agent's gated actions
  (exec / findings / setup / observe / destroy) return **`423 Locked`**.
- `POST /arenas/{id}/bindings/{agent_name}/resume` → `{ "paused": false, … }`.
  Operator-only, idempotent. The agent may drive the arena again.
Pause/resume are event-backed (`agent_binding_paused` / `agent_binding_resumed`);
a fresh grant or a revoke also clears the paused state.

`403` for an `agent` caller · `404` unknown arena or no active binding (for
pause/resume) · `422` unknown stance · `423` action attempted while paused.

The **operator console** surfaces these on the arena detail page (the *Agent
bindings* panel: list / grant / pause / resume / revoke) and in the **Agents**
page agent-config modal (Pause / Resume / Kill) — no curl needed.

### Model connection (operator's bring-your-own key)

The operator configures their **bring-your-own model** (provider + model + API
key) once, from the console's model bubble. The key is **encrypted at rest**
(Fernet) and bound to the operator principal; the connection sits in **standby**
("active but waiting") until a feature needs it — the scenario generator or an
arena whose mode uses an agent in a stance. Nidavellir custodies the key and
provides the connection; the model stays the operator's (scope boundary). **All
three are operator/admin only — an `agent`-role key gets `403`** (an agent must
never read or manage the credential; activators decrypt it server-side, never
over HTTP).

- `PUT /agent/model` — store/replace the connection. The key is never logged and
  never returned. Known providers: `anthropic`, `openai`, `gemini`, `deepseek`,
  `ollama`, `local` (the last two may run keyless). On update, a **blank
  `api_key` keeps the stored key** (so you can change the model without
  re-entering the key).
  ```json
  { "provider": "anthropic", "model": "claude-opus-4-8", "api_key": "sk-…" }
  → { "configured": true, "provider": "anthropic", "model": "claude-opus-4-8",
      "key_last4": "…1a2b", "status": "standby", "updated_at": "…" }
  ```
  `422` unknown provider, or a cloud provider with no key.
- `GET /agent/model` — the **masked** connection (`key_last4` only, never the
  key), or `{ "configured": false }`.
- `DELETE /agent/model` — forget the stored credential (`{ "removed": true|false }`).
- `POST /agent/model/verify` — **best-effort liveness check** of a key (lists the
  provider's models — no inference, no agent run). With `{provider, model, api_key}`
  it tests the supplied key (pre-save); with `{}` it tests the stored one. Returns
  `{verified, detail, checked}` — `checked:false` means *couldn't reach a verdict*
  (no egress / unknown host), distinct from `verified:false` (key rejected). Never
  blocks or stores anything.
- `POST /agent/chat` `{arena_id?, messages:[{role,content}]}` — the **co-pilot**:
  streams a reply from the operator's connected model (decrypted in-process, never
  logged) with the arena's context injected (scenario, topology, setup state,
  recent activity, benchmark progress). **Advise-only** (no tools), operator-only,
  `text/plain` chunked stream. `409` if no model is connected.

### SUT arena wizard

`POST /arenas/sut` (operator-only) provisions a software-under-test arena from a
GitHub repo (cloned read-write into a fresh Ubuntu victim at `/opt/sut`, optional
Kali foothold); the setup config (`mode`/`time_box_seconds`/`command_budget`/
`setup_egress`) is captured as consent and the setup session auto-opens when the
arena is active. `POST /arenas/sut/preview` (operator-only) compiles the same spec
and returns `{valid, summary, topology, warnings}` **without deploying** — the
review gate the WebUI **Wizard** (`/wizard`) uses to show the planned topology
before launch.

The request must also carry `authorization_confirmed: true` and an
`authorization_basis` of `public_oss`, `owned`, or `authorized_assessment`;
`scope_note` optionally records a ticket, agreement, policy, or other scope
reference. Launch fails closed without confirmation. The requested branch/tag is
resolved once and the compiled scenario is pinned to the resulting Git object ID,
returned as `target_manifest.resolved_ref`. A missing or invalid ref is a `422`;
the platform never silently falls back to the repository's default branch.

`POST /arenas/oci/preview` and `POST /arenas/oci` provide the packaged-target
counterpart. The request shape is `{instance_id, image, ports?,
include_attacker?, platform?, authorization_basis, authorization_confirmed,
scope_note?}`. `platform` is explicit (`linux/amd64` by default or
`linux/arm64`) so an immutable multi-architecture index cannot select different
binaries on different benchmark hosts.
This phase accepts public, anonymously pullable Docker/OCI Registry v2 images.
A tag such as `nginx:1.27` is resolved through the registry API and the scenario
receives only `docker.io/library/nginx@sha256:…`; a supplied digest is verified
against the registry. Redirects, local/private registry hosts, non-HTTPS token
realms, mutable runtime tags, and private-registry credentials are not accepted.
Preview performs metadata calls only—it does not pull or execute the image.

OCI targets run their published entrypoint without the generic shell keepalive,
so distroless images work and the artifact is not behaviorally modified. An image
that exits is reported by the same fail-closed preflight and the configurator is
not opened for packaged OCI targets.

Local source bundles use a two-step content-addressed flow:

1. `POST /targets/source-bundles` (operator-only multipart field `file`) accepts
   `.tar`, `.tar.gz`, or `.tgz` and returns `{artifact: {digest,
   payload_digest, filename, upload_bytes, expanded_bytes, file_count, ...}}`.
2. `POST /arenas/source-bundle/preview` or `POST /arenas/source-bundle` accepts
   `{instance_id, artifact_digest, ports?, include_attacker?, setup_mode?,
   time_box_seconds?, command_budget?, setup_egress?, authorization_basis,
   authorization_confirmed, scope_note?}`.

The upload is streamed and independently bounded by compressed size, expanded
size, per-file size, member count, path length/depth, and total artifact-store
capacity. Intake rejects traversal, absolute paths, duplicate/colliding names,
`.git`, links, sparse files, devices and other special members. It never extracts
onto the control-plane filesystem or executes bundle content. A sanitized
canonical tar is hashed and stored atomically; the worker re-verifies that payload
before sending it through the Docker API to a networkless helper and an
arena-owned volume. The helper creates a clean Git baseline, enabling the same
GUI/MCP diff contract as Git intake. Build/install commands remain confined to
the consent-gated disposable setup target.

Both introspect the repo (M1-1) — detected language / build system / declared
ports / base runtime — and plan the deterministic build tier (M1-2, ADR-0008), so
the response carries `introspection` + `build_plan`. When the repo ships a
`Dockerfile` and source builds are enabled (`NIDAVELLIR_ALLOW_SOURCE_BUILD=true`),
the victim **auto-builds to a version-pinned image** (`build_plan.auto_build`);
otherwise the bare-Ubuntu + configurator flow is used. `compose` / `devcontainer` /
`buildpack` are detected but their execution is deferred (see ADR-0008).

`GET /arenas/{id}/preflight` returns the Git or OCI target manifest, reset contract, and the
latest infrastructure checks: immutable identity, authorization, healthy target
node, requested foothold, provider workspace, and reset reproducibility. During
deployment it returns `status: pending`; after provisioning it is `passed` or
`failed`. A failed required check prevents the pre-armed configurator session from
opening.

`POST /repos/synthesize-dockerfile` (operator-only) is the **tier-3 fallback** for a
repo that ships no Dockerfile/compose/devcontainer (M1-3, Repo2Run): the operator's
own connected model drafts a Dockerfile grounded in the introspection, the platform
**actually builds it**, feeds any build error back to the model to fix, and returns
only one that **built green** (`{ok, dockerfile, attempts, introspection, build_plan}`)
— never an unverified Dockerfile, never an auto-deploy. Requires a connected model
and source builds enabled (409 otherwise). Body: `{repo, ref?, max_attempts?}`.

### Configurator setup phase (SUT arenas)

Bring an arbitrary OSS service up on the victim node before an engagement
(ADR-0007 / P2-10). The orchestrator is the single enforcement point: **consent**
(operator-only `start`, which picks the `mode`), **victim-scope** (foothold/attacker
nodes can never be targeted), **time-box** (auto-revoked on expiry), **step budget**,
and full **audit** (`setup_session` / `setup_step` / `setup_proposal` /
`setup_proposal_decision` / `setup_finished` events — no migration). The phase is an
event-backed overlay on an ACTIVE arena (`provisioning → setup → ready → engagement`).
Three **modes** (the consent choice): `operator` (the operator scripts steps — the
**AI-optional** path), `hitl` (an agent proposes each step, the operator approves), and
`autonomous` (an agent runs steps directly — **double-locked**, see below).

**Operator controls** (operator/admin only; `agent` → 403):

- `POST /arenas/{id}/setup/start` `{nodes?, time_box_seconds?, command_budget?, setup_egress?, mode?, agent_name?}`
  — open a session. `nodes` defaults to all non-foothold nodes; a foothold in scope
  → `422`. `agent_name` **binds that agent key** to the arena as `configurator` for
  the session (D1 — the agent must be bound to drive HITL/autonomous setup); the
  binding is **revoked at `finish`**. `setup_egress:true` opens **real internet
  egress** on the victim for the session (so any dependency — git/npm/go/cargo/distro
  — can be fetched), via a per-arena NAT bridge; it is **revoked before the
  engagement** (on finish, on expiry, and by the reaper) so the runtime stays
  egress-locked. `501` if the provider can't toggle egress (docker-local can).
  `mode:"autonomous"` → `403` unless the platform flag
  `NIDAVELLIR_ALLOW_AUTONOMOUS_CONFIGURATOR` is set (the **double lock**: flag +
  this explicit per-arena consent).
- `GET /arenas/{id}/setup` — `{open, expired, mode, nodes, steps_run, budget_remaining, egress_enforced, pending_proposals, …}`.
- `POST /arenas/{id}/setup/step` `{node, command, timeout?}` — operator-scripted direct
  step. Enforces scope (`403`), budget (`429`), time-box (`409` + auto-close on expiry).
- `GET /arenas/{id}/setup/proposals` — list HITL proposals awaiting a decision.
- `POST /arenas/{id}/setup/proposals/{step_id}/approve` — **approve** a proposed step →
  it runs on the victim and the result is recorded (the load-bearing HITL gate).
- `POST /arenas/{id}/setup/proposals/{step_id}/reject` — reject (it never runs).
- `POST /arenas/{id}/setup/generate-proposals` (operator-only, **HITL**) — draft setup
  steps using the **operator's own connected model** and record them as pending
  `setup_proposal`s for approval (the gate is unchanged — the model only drafts,
  nothing runs without approval). For when you don't have a configurator-stance agent
  connected. `409` without an open hitl session or a connected model; capped at the
  remaining step budget; out-of-scope/empty steps are dropped.

**Configurator-agent tools** (the gateway `stance=configurator` backend; reachable by an
`agent` key but gated by a **`configurator` binding** to the arena (D1) + an open session
+ mode + scope + budget + time-box):

- `GET /arenas/{id}/setup/brief` — victim node(s) in scope, white-box source path, mode, budget.
- `POST /arenas/{id}/setup/propose` `{node, command, rationale?}` — **HITL**: propose a step
  (pending until the operator approves). `409` unless `mode='hitl'`; `403` out-of-scope.
- `GET /arenas/{id}/setup/proposals/{step_id}` — await a proposal: `pending | approved` (with the exec result) `| rejected`.
- `POST /arenas/{id}/setup/run` `{node, command, timeout?}` — **autonomous**: run a step
  directly. Double-locked (`409` unless `mode='autonomous'`; `403` unless the platform flag is set).
- `POST /arenas/{id}/setup/upload` `{node, path, content_b64}` — write a file on the victim
  (config/seed/patch) via the gated exec path (scoped + budgeted + audited).
- `POST /arenas/{id}/setup/finish` — close the session, revoke egress + the configurator
  capability (callable by the operator or the configurator agent).

### Findings, deterministic validation & structured scoring (M2/M3, ADR-0009/0010)

Two scoring modes. **Benchmark**: a scenario plants a hidden **known-vulnerability
manifest** (ground truth) and self-reported findings are matched + verified against
it. **Discovery** (custom / SUT arenas, no manifest): the agent's findings and the
crash-oracle signals are scored directly — "the agent made it fall over" is
first-class evidence. The manifest is operator-only and never shown to an agent.

- `GET /scenarios/{scenario_id}/vulnerabilities` — **reveal** the manifest (the
  benchmark baseline). **operator/admin only** (`403` for an `agent` key); `404`
  unknown scenario.
- `POST /arenas/{instance_id}/findings` — an attacker self-reports a finding (the
  MCP `report_finding` backend). Matched against the hidden manifest by **CWE +
  node**, and **deterministically verified** (ADR-0009 item 6): supply the optional
  proof inputs and the platform confirms the finding against the arena — a
  reflected-XSS nonce executed in the arena browser (`path`+`param`), an injected
  marker, an OAST callback (`oast_token`), or passive crash-oracle correlation.
  The match **and** the verdict are recorded operator-only; the response stays a
  neutral ack (no oracle — the agent can't learn whether it worked).
  Include a **`poc`** — a reproducible proof (a `curl`/HTTP request, shell command,
  or numbered steps) a human can run to verify the finding. It is recorded and
  shown to the operator next to the confirm/refute controls (agent-visible, since
  it's the reporter's own repro — not ground truth).
  ```json
  { "title": "SQLi on login", "cwe": "CWE-89", "node": "victim",
    "path": "/vulnerabilities/sqli/", "param": "id", "payload": "1' OR '1'='1",
    "poc": "curl \"http://victim/vulnerabilities/sqli/?id=1' OR '1'='1\" | grep admin",
    "evidence": "...",
    "evidence_artifact_digests": ["sha256:0123..."] }
  → { "recorded": true, "finding_id": "7097421dd9fc" }
  ```
  Each digest must name an artifact from the same arena. Findings persist a
  verified metadata reference, letting operators download the exact patch used
  as evidence without copying its body into the finding event.
- `POST /arenas/{instance_id}/findings/manual` — an **operator-entered** finding
  (a vuln a human found, or one to put on the record). Same body + manifest match +
  verification as `report_finding`, but flagged `manual` and attributed to the
  operator. **operator/admin only.**
- `POST /arenas/{instance_id}/findings/{finding_id}/verify` — the **human
  verification path** (ADR-0009 item 6). Records an operator verdict on a reported
  finding; an operator `confirmed` counts as a deterministic confirmation (flips the
  `verified_exploit` milestone and adds `confirmed_points`), `refuted` marks it
  unconfirmed. The newest verdict per finding wins and overrides any auto-verdict.
  **operator/admin only.**
  ```json
  { "verdict": "confirmed", "note": "UNION dump reproduced" }
  → { "verified": true, "finding_id": "7097421dd9fc", "verdict": "confirmed" }
  ```
- `GET /arenas/{instance_id}/score[?mode=benchmark|discovery]` — the structured,
  Inspect-style **scorecard**. **operator/admin only**. Mode auto-selects on the
  manifest's presence (overridable via `?mode=`). Carries the typed `score`
  (`value` + `answer` + `explanation` + `evidence` + `metadata`), a milestone
  **Progress Rate** (`milestones[]`, `progress_rate`, `tier`) that scores even a
  failed run, the benchmark view (`found`/`missed`/`confirmed`/`points_*`), the
  discovery view (`signals` = crash-oracle counts + `distinct_fault_sites`,
  `confirmed_findings`), and derived `metrics` (steps, wall-clock).
- `GET /arenas/{instance_id}/eval-export[?mode=…]` (M3, ADR-0010) — project the run
  into a Langfuse/Phoenix-ready **eval-dataset row**: `input` / `expected_output`
  (the manifest — ground truth) / `metadata` (the model+scaffold+cost+`pass@1`
  tuple) / `tags` / `source_trace_id` + the embedded `score`. **operator/admin
  only.**

### Service-under-test monitor (M2, ADR-0009)

A Celery-beat task (`monitor_arenas`, every `NIDAVELLIR_MONITOR_INTERVAL_SECONDS`,
default 30s) polls each **ACTIVE** arena, reads its service-under-test nodes'
container state + a bounded log tail from the provider, and runs a crash oracle
(`monitor.detect_signals`). Any **new** signal is appended to the audit stream as
a `monitor_signal` event (`actor: "monitor"`) — so a target with **no known-CVE
manifest is still scorable**, and the signals surface to the defender stance's
`query_events` feed and the operator console with no extra endpoint. There is no
request API; the monitor runs on the schedule. Signal kinds: `crash`,
`sanitizer_abort`, `unhandled_5xx`, `resource_exhaustion`. Payload:

```json
{ "kind": "crash", "node": "victim", "severity": "high",
  "summary": "victim exited with a non-zero status (139)",
  "evidence": "...last log lines...", "key": "crash:victim:178cde5de027" }
```

`key` deduplicates a persistent fault so it is recorded once, not on every tick.
Only `docker-local`/`mock` collect today (VM/cloud providers refuse cleanly until
M8). The deterministic validators that *confirm* a finding before it is credited,
and the structured scored verdict, are the rest of M2 (items 6–7, ADR-0009).

### Response Format

All responses are JSON with the following structure:

**Success:**
```json
{
  "status": "accepted",
  "instance_id": "lab-team-1"
}
```

**Error:**
```json
{
  "detail": "Instance ID already exists"
}
```


## Endpoints

### 1. Deploy Lab

Queue a new infrastructure deployment.

**Request:**
```http
POST /deploy
Content-Type: application/json
```

**Body:**
```json
{
  "scenario": "basic_pentest",
  "instance_id": "lab-team-1",
  "provider": "openstack"
}
```

**Parameters:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario` | string | Yes | Scenario name (e.g., `basic_pentest`, `random_vulnhub`) |
| `instance_id` | string | Yes | Unique identifier for this lab (alphanumeric + hyphens) |
| `provider` | string | No | Deployment backend (see `GET /providers`). Omitted → the install default (worker's `RANGE_PROVIDER` / `MOCK_MODE`). The chosen provider is recorded with the deployment, and destroy always runs on the provider the lab was deployed with. |

**Response:** `202 Accepted`
```json
{
  "status": "accepted",
  "instance_id": "lab-team-1"
}
```

**Error Responses:**
- `400 Bad Request`: Instance ID already exists or invalid format
- `422 Unprocessable Entity`: unknown `provider`, or the scenario's
  `provider_class` doesn't match the provider's `infra_class`
  (e.g. a `vm` scenario on `docker-local`)
- `500 Internal Server Error`: Worker unavailable

**Example:**
```bash
curl -X POST http://localhost:8000/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario": "basic_pentest",
    "instance_id": "lab-team-1"
  }'
```

---

### 2. List All Labs

Retrieve all active and historical deployments.

**Request:**
```http
GET /deployments
```

**Response:** `200 OK`
```json
{
  "lab-team-1": {
    "status": "active",
    "scenario": "basic_pentest",
    "outputs": {
      "attack_vm_floating_ip": "192.168.1.80",
      "log_vm_floating_ip": "192.168.1.50",
      "victim_vm_floating_ip": "192.168.1.60",
      "soc_dashboard_url": "https://192.168.1.50:5601",
      "soc_credentials": {
        "username": "cyberrange-admin",
        "password": "CyberRange2024!"
      }
    }
  },
  "lab-team-2": {
    "status": "deploying",
    "scenario": "basic_pentest",
    "outputs": {}
  }
}
```

**Example:**
```bash
curl http://localhost:8000/deployments
```

---

### 3. Get Lab Status

Poll this endpoint to check deployment progress and retrieve IPs/credentials.

**Request:**
```http
GET /status/{instance_id}
```

**Path Parameters:**
| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | string | Lab identifier |

**Response:** `200 OK`
```json
{
  "status": "active",
  "scenario": "basic_pentest",
  "provider": "openstack",
  "created_at": "2025-01-24T14:30:00",
  "updated_at": "2025-01-24T14:45:00",
  "outputs": {
    "attack_vm_private_ip": "192.168.50.10",
    "attack_vm_floating_ip": "192.168.1.80",
    "attack_vm_ssh_command": "ssh -i nidavellir_ssh_key.pem kali@192.168.1.80",
    
    "log_vm_private_ip": "192.168.0.5",
    "log_vm_floating_ip": "192.168.1.50",
    "log_vm_ssh_command": "ssh -i nidavellir_ssh_key.pem ubuntu@192.168.1.50",
    
    "victim_vm_private_ip": "192.168.0.10",
    "victim_vm_floating_ip": "192.168.1.60",
    
    "soc_dashboard_url": "https://192.168.1.50:5601",
    "soc_credentials": {
      "username": "cyberrange-admin",
      "password": "CyberRange2024!"
    }
  },
  "error": null
}
```

> **Secrets at rest.** `outputs` contains credentials (e.g. `soc_credentials`)
> and access details. When `SECRETS_ENCRYPTION_KEY` is set on the stack, this
> blob is encrypted at rest in the database and decrypted only for API
> responses — so the values you see here are plaintext, but a leaked DB file
> is not. Without the key, outputs are stored in plaintext. See
> [SECURITY.md](SECURITY.md#secrets-handling-audit-14).

**Status Values** (transitions are enforced by a state machine — ADR-0004):
| Status | Description |
|--------|-------------|
| `pending` | Task queued, waiting for worker |
| `deploying` | Provisioning in progress |
| `active` | Infrastructure ready, outputs available |
| `destroying` | Cleanup in progress |
| `destroyed` | Terminal: infrastructure gone (record deletable) |
| `failed` | Deployment failed (check `error` field) |
| `error_destroying` | Cleanup failed (check `error`; destroy again to retry) |

### Lab TTL & the reaper

Every deployment gets an expiry (`expires_at` in the status response),
`created_at + LAB_TTL_MINUTES` (default 180). A Celery-beat **reaper** runs
every `REAPER_INTERVAL_SECONDS` (default 300) and:

- **destroys expired labs** (TTL elapsed) — guards against cost/quota leak;
- **reconciles stuck labs** — a lab sitting in `pending`/`deploying`/
  `destroying` with no progress for `LAB_STUCK_MINUTES` (default 30) is
  treated as orphaned (its worker is gone) and driven to destruction.

Reaper actions are recorded as `reaped` events (with the reason) in the audit
stream. A lab with no `expires_at` (e.g. legacy rows) is never auto-expired,
but is still covered by the stuck-reconciliation path.

**Error Response:** `404 Not Found`
```json
{
  "detail": "Instance not found"
}
```

**Example:**
```bash
# Poll every 5 seconds until active
while true; do
  curl http://localhost:8000/status/lab-team-1 | jq '.status'
  sleep 5
done
```

---

### 4. Destroy Lab

Queue infrastructure destruction and workspace cleanup.

Operators/admins may destroy any arena. An `agent` principal must hold an active
binding to this arena; an unbound agent receives `403`, and a paused binding
receives `423`.

**Request:**
```http
DELETE /destroy/{instance_id}
```

**Path Parameters:**
| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | string | Lab identifier |

**Response:** `200 OK`
```json
{
  "status": "accepted"
}
```

**Error Responses:**
- `403 Forbidden`: agent key is not bound to this arena
- `423 Locked`: the agent's arena binding is paused
- `404 Not Found`: unknown instance
- `409 Conflict`: the lab is already destroyed (lifecycle state machine,
  ADR-0004) — delete its record instead if you want it gone from history

**Example:**
```bash
curl -X DELETE http://localhost:8000/destroy/lab-team-1
```

---

### 5. Delete Lab Record

Remove one lab's record from history. Only terminal-state labs
(`destroyed`, `failed`, `error_destroying`) can be deleted — a live lab
must be destroyed first. Operator/admin only.

**Request:**
```http
DELETE /deployments/{instance_id}
```

**Response:** `200 OK`
```json
{
  "status": "deleted"
}
```

**Error Responses:**
- `403 Forbidden`: operator/admin role required
- `404 Not Found`: unknown instance
- `409 Conflict`: the lab is still live (destroy it first)

---

### 6. Purge Archived Records

Remove **all** terminal-state (`destroyed`/`failed`/`error_destroying`)
lab records at once. Live labs are untouched. Operator/admin only; an agent key
receives `403`.

**Request:**
```http
DELETE /deployments
```

**Response:** `200 OK`
```json
{
  "status": "purged",
  "deleted": 7
}
```



## Workflow example

### Complete Deployment Lifecycle
```bash
# 1. Deploy a new lab
curl -X POST http://localhost:8000/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario": "basic_pentest",
    "instance_id": "lab-prod-001"
  }'

# Response: {"status": "accepted", "instance_id": "lab-prod-001"}

# 2. Poll for status (repeat until status == "active")
curl http://localhost:8000/status/lab-prod-001 | jq

# Initial: {"status": "pending", "outputs": {}}
# After 30s: {"status": "deploying", "outputs": {}}
# After 10min: {"status": "active", "outputs": {...}}

# 3. Extract SSH command
curl http://localhost:8000/status/lab-prod-001 | \
  jq -r '.outputs.attack_vm_ssh_command'

# Output: ssh -i nidavellir_ssh_key.pem kali@192.168.1.80

# 4. Access Wazuh dashboard
curl http://localhost:8000/status/lab-prod-001 | \
  jq -r '.outputs.soc_dashboard_url'

# Output: https://192.168.1.50:5601

# 5. When done, destroy
curl -X DELETE http://localhost:8000/destroy/lab-prod-001
```

---

## Output fields reference

### Attack VM (Kali Linux)
- `attack_vm_name`: VM hostname
- `attack_vm_private_ip`: Internal network IP
- `attack_vm_floating_ip`: Public IP for SSH access
- `attack_vm_ssh_command`: Ready-to-use SSH command

### SOC/Monitor VM
- `log_vm_name`: VM hostname
- `log_vm_private_ip`: Internal network IP
- `log_vm_floating_ip`: Public IP for SSH/dashboard access
- `log_vm_ssh_command`: SSH access command
- `soc_dashboard_url`: Wazuh web interface URL
- `soc_credentials`: Login credentials for Wazuh

### Victim VM
- `victim_vm_name`: VM hostname
- `victim_vm_private_ip`: Internal network IP
- `victim_vm_floating_ip`: Public IP

### Network Info
- `private_network_cidr`: Internal subnet (e.g., `192.168.0.0/24`)
- `private_network_name`: OpenStack network name
- `router_name`: OpenStack router name



## Performance notes

### Timeouts
- **Deployment:** 15-30 minutes (depending on cloud provider)
- **Destruction:** 2-5 minutes
- **API Response:** < 100ms (async task dispatch)

### Rate Limits
- `POST /deploy`: **10/minute** per client (`RATE_LIMIT_DEPLOY`)
- `DELETE /destroy/...`: **30/minute** per client (`RATE_LIMIT_DESTROY`)
- Exceeding a limit returns `429 Too Many Requests`
- Reads are unlimited; still, poll `/status` no faster than every 3 seconds

### Concurrency
- **Default:** 3 concurrent deployments
- **Configurable:** `WORKER_CONCURRENCY` environment variable





## Testing with mock mode

When `MOCK_MODE=true`, deployments simulate infrastructure without real provisioning:
```bash
# Start API in mock mode
export MOCK_MODE=true
uvicorn api:app --host 0.0.0.0 --port 8000

# Deploy returns fake IPs immediately
curl -X POST http://localhost:8000/deploy \
  -d '{"scenario": "basic_pentest", "instance_id": "test-1"}'

# Status shows fake outputs after ~2 seconds
curl http://localhost:8000/status/test-1
```

**Mock Outputs:**
- Realistic IP addresses (192.168.x.x)
- Fake SSH commands
- Simulated credentials
- No actual infrastructure created
