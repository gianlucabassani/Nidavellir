# 🔌 CyberGuard API Reference

Base URL: `http://localhost:8000`



## 📋 Overview

The CyberGuard API provides RESTful endpoints for managing cyber range deployments.
 All operations are **asynchronous**.

### Authentication

All endpoints except `GET /health` require an API key in the `X-API-Key`
header (see [ADR-0002](adr/0002-api-authentication.md)):

```bash
export CYBERGUARD_API_KEY=cg_...   # create one: python auth.py create-key <name> <role>
curl -H "X-API-Key: $CYBERGUARD_API_KEY" http://localhost:8000/deployments
```

Roles: `admin`, `instructor`, `student`, `agent` (recorded for auditing;
fine-grained enforcement arrives with multi-tenancy). Missing or invalid keys
get `401`. The docker-compose stack bootstraps the key from the
`CYBERGUARD_API_KEY` value in `.env` — the default `dev-insecure-key` is for
the local mock demo only.

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
      "name": "Mr. Robot CTF Scenario",
      "description": "…",
      "difficulty": "medium",
      "tags": []
    }
  ]
}
```

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
  "instance_id": "lab-team-1"
}
```

**Parameters:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario` | string | Yes | Scenario name (e.g., `basic_pentest`, `random_vulnhub`) |
| `instance_id` | string | Yes | Unique identifier for this lab (alphanumeric + hyphens) |

**Response:** `202 Accepted`
```json
{
  "status": "accepted",
  "instance_id": "lab-team-1"
}
```

**Error Responses:**
- `400 Bad Request`: Instance ID already exists or invalid format
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

**Status Values:**
| Status | Description |
|--------|-------------|
| `pending` | Task queued, waiting for worker |
| `deploying` | Terraform provisioning in progress |
| `active` | Infrastructure ready, outputs available |
| `destroying` | Cleanup in progress |
| `failed` | Deployment failed (check `error` field) |

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

**Error Response:** `404 Not Found`
```json
{
  "detail": "Instance not found"
}
```

**Example:**
```bash
curl -X DELETE http://localhost:8000/destroy/lab-team-1
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

### Victim VM (Mr. Robot)
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
