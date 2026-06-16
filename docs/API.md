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
tool proxies (foothold-scope is enforced at the gateway; this endpoint is the
raw infra primitive). Synchronous; provider-enforced (`docker exec`, SSH for VM
providers once wired). **Every exec is written to the `events` audit trail.**

```json
{ "node": "jump", "command": "nmap -sV 10.0.0.2", "timeout": 30 }
→ { "node": "jump", "exit_code": 0, "stdout": "...", "stderr": "" }
```

`404` unknown arena/node · `409` arena not `active` · `501` provider has no exec
(VM providers, for now) · `422` empty command or out-of-range timeout (1–120s).
Output is capped; the command is bounded to 4096 chars.

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
