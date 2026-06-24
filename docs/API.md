# 🔌 CyberGuard API Reference

Base URL: `http://localhost:8000`



## 📋 Overview

The CyberGuard API provides RESTful endpoints for managing arena deployments.
 All operations are **asynchronous**.

### Authentication

All endpoints except `GET /health` require an API key in the `X-API-Key`
header (see [ADR-0002](adr/0002-api-authentication.md)):

```bash
export CYBERGUARD_API_KEY=cg_...   # create one: python auth.py create-key <name> <role>
curl -H "X-API-Key: $CYBERGUARD_API_KEY" http://localhost:8000/deployments
```

Roles: `admin` (manage platform/keys), `operator` (author/run/observe
engagements), `agent` (the AI under test). Recorded for auditing; per-owner
enforcement arrives with hardening (ROADMAP Phase 5). Missing or invalid keys
get `401`. The docker-compose stack bootstraps the key from the
`CYBERGUARD_API_KEY` value in `.env` — the default `dev-insecure-key` is for
the local mock demo only.

> The role set is `admin` / `operator` / `agent` (the legacy
> `instructor`/`student` were renamed to `operator` in the 2026-06 pivot; keys
> issued with the old roles still authenticate). `attacker`/`MITM`/`defender`
> are per-session agent **stances** (chosen via the MCP gateway), not auth roles.

> All examples below assume `-H "X-API-Key: $CYBERGUARD_API_KEY"` is added.

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
`CYBERGUARD_ALLOW_SOURCE_BUILD`); a Kali foothold is added unless
`include_attacker: false`. Lossy conversions (dropped `volumes`/`depends_on`/…)
are returned in `warnings`. `dry_run: true` previews (validate + topology) without
saving; otherwise the pack is persisted and appears in `GET /scenarios`. VulnHub
(full VM disks) is a separate, planned track. Returns `422` on an unconvertible
compose, `409` on an id collision (pass `overwrite: true`).

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
`announce_agent` tool proxies; the model/provider are self-declared (CyberGuard
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
- `GET /arenas/{id}/bindings` → `{ "bindings": [ … ] }` (active bindings).
  Operator-only.
- `DELETE /arenas/{id}/bindings/{agent_name}` → `{ "revoked": true|false }`.
  Operator-only; idempotent.

`403` for an `agent` caller · `404` unknown arena · `422` unknown stance.

### Model connection (operator's bring-your-own key)

The operator configures their **bring-your-own model** (provider + model + API
key) once, from the console's model bubble. The key is **encrypted at rest**
(Fernet) and bound to the operator principal; the connection sits in **standby**
("active but waiting") until a feature needs it — the scenario generator or an
arena whose mode uses an agent in a stance. CyberGuard custodies the key and
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
  `CYBERGUARD_ALLOW_AUTONOMOUS_CONFIGURATOR` is set (the **double lock**: flag +
  this explicit per-arena consent).
- `GET /arenas/{id}/setup` — `{open, expired, mode, nodes, steps_run, budget_remaining, egress_enforced, pending_proposals, …}`.
- `POST /arenas/{id}/setup/step` `{node, command, timeout?}` — operator-scripted direct
  step. Enforces scope (`403`), budget (`429`), time-box (`409` + auto-close on expiry).
- `GET /arenas/{id}/setup/proposals` — list HITL proposals awaiting a decision.
- `POST /arenas/{id}/setup/proposals/{step_id}/approve` — **approve** a proposed step →
  it runs on the victim and the result is recorded (the load-bearing HITL gate).
- `POST /arenas/{id}/setup/proposals/{step_id}/reject` — reject (it never runs).

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

### Known-vulnerability manifest, findings & scoring

The benchmark model (replaces CTF flags): a scenario plants a **known-vulnerability
manifest** (ground truth). The agent's goal is to **discover** those vulnerabilities;
the manifest is operator-only and never shown to an agent.

- `GET /scenarios/{scenario_id}/vulnerabilities` — **reveal** the manifest (the
  benchmark baseline). **operator/admin only** (`403` for an `agent` key); `404`
  unknown scenario.
- `POST /arenas/{instance_id}/findings` — an attacker self-reports a finding
  (the MCP `report_finding` backend). Matched against the hidden manifest by
  **CWE + node**; the match is recorded for scoring but the response is a neutral
  ack (no oracle — the agent can't learn whether it was right).
  ```json
  { "title": "SQLi on login", "cwe": "CWE-89", "node": "victim", "evidence": "..." }
  → { "recorded": true, "finding_id": "7097421dd9fc" }
  ```
- `GET /arenas/{instance_id}/score` — **scorecard**: `found`/`missed` vuln ids,
  `points_earned`/`points_total`, `findings_submitted`, and the `manifest`.
  **operator/admin only** (`403` for an `agent` key).

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
    "attack_vm_ssh_command": "ssh -i cyberguard_ssh_key.pem kali@192.168.1.80",
    
    "log_vm_private_ip": "192.168.0.5",
    "log_vm_floating_ip": "192.168.1.50",
    "log_vm_ssh_command": "ssh -i cyberguard_ssh_key.pem ubuntu@192.168.1.50",
    
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

# Output: ssh -i cyberguard_ssh_key.pem kali@192.168.1.80

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
