# 🔌 Nidavellir API Reference

Base URL: `http://localhost:8000`



## 📋 Overview

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
enforcement arrives with hardening (ROADMAP Phase 5). Missing or invalid keys
get `401`. The docker-compose stack bootstraps the key from the
`NIDAVELLIR_API_KEY` value in `.env` — the default `dev-insecure-key` is for
the local mock demo only.

> The role set is `admin` / `operator` / `agent` (the legacy
> `instructor`/`student` were renamed to `operator` in the 2026-06 pivot; keys
> issued with the old roles still authenticate). `attacker`/`MITM`/`defender`
> are per-session agent **stances** (chosen via the MCP gateway), not auth roles.

> All examples below assume `-H "X-API-Key: $NIDAVELLIR_API_KEY"` is added.

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
**drive** an arena (exec / report findings / configure the victim), and in what
stance. Without a binding an agent key cannot touch an arena it has no
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
`configurator` → setup steps; `defender`/`mitm` → reads only. Operators/admins
are never bound and bypass every check.

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
  (exec / findings / setup / observe) return **`423 Locked`**.
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

Both introspect the repo (M1-1) — detected language / build system / declared
ports / base runtime — and plan the deterministic build tier (M1-2, ADR-0008), so
the response carries `introspection` + `build_plan`. When the repo ships a
`Dockerfile` and source builds are enabled (`NIDAVELLIR_ALLOW_SOURCE_BUILD=true`),
the victim **auto-builds to a version-pinned image** (`build_plan.auto_build`);
otherwise the bare-Ubuntu + configurator flow is used. `compose` / `devcontainer` /
`buildpack` are detected but their execution is deferred (see ADR-0008).

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
  reflected-XSS nonce reflected unescaped (`path`+`param`+`payload`), an injected
  marker, an OAST callback (`oast_token`), or passive crash-oracle correlation.
  The match **and** the verdict are recorded operator-only; the response stays a
  neutral ack (no oracle — the agent can't learn whether it worked).
  ```json
  { "title": "SQLi on login", "cwe": "CWE-89", "node": "victim",
    "path": "/vulnerabilities/sqli/", "param": "id", "payload": "1' OR '1'='1",
    "evidence": "..." }
  → { "recorded": true, "finding_id": "7097421dd9fc" }
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


## 🚀 Endpoints

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
must be destroyed first.

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
- `404 Not Found`: unknown instance
- `409 Conflict`: the lab is still live (destroy it first)

---

### 6. Purge Archived Records

Remove **all** terminal-state (`destroyed`/`failed`/`error_destroying`)
lab records at once. Live labs are untouched.

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



## 📊 Workflow Example

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

## 🔍 Output Fields Reference

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



## ⚡ Performance Notes

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





## 🧪 Testing with Mock Mode

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
