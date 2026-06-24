# Nidavellir — setup & operations

Detailed run/operate notes. For what Nidavellir is and the roadmap, see the
[top-level README](../README.md).

## Run the stack (Docker, recommended)

The dev stack runs everything — orchestrator, worker, Redis, console — in Docker,
with **mock mode pinned** and live source reload. No `.env` required.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# Console: http://localhost:5000   (login: admin / nidavellir)
# API:     http://localhost:8000   (header: X-API-Key: dev-insecure-key)
docker compose -f docker-compose.yml -f docker-compose.dev.yml down   # stop
```

`make check` runs the gate (ruff + bandit + pytest, mock mode — no Redis needed).

## Deployment modes

The provider is chosen per request or by the worker's environment:

| Mode | Set | Result |
|------|-----|--------|
| **Mock** | `MOCK_MODE=true` | Fake outputs, instant — demoable with no infrastructure. |
| **Container** | `MOCK_MODE=false`, `RANGE_PROVIDER=docker-local`, mount the Docker socket | Real per-arena container topologies on the local daemon (seconds, zero cloud cost). |
| **OpenStack / AWS** | `MOCK_MODE=false` + provider credentials | Real VMs via the generic `nodes[]` Terraform/OpenTofu modules. |

Egress containment is **default-on** for locked arenas (a node cannot reach the
internet); opt out per scenario with `requires.egress: open`. See
[`SECURITY.md`](SECURITY.md).

## Run the services manually (without Docker)

Four processes — Redis, the Celery worker, the FastAPI orchestrator, the Flask console:

```bash
# 0. Prereqs: Python 3.10+, Redis, (OpenTofu/Terraform only for VM providers)
mkdir -p data runs cache/terraform-plugins keys
redis-server &   # or: docker run -d -p 6379:6379 redis:alpine

# 1. Worker
cd cyber-range/services/scenario-orchestrator
pip install -r requirements.txt
MOCK_MODE=true celery -A tasks worker --loglevel=info --concurrency=3 &

# 2. Orchestrator API
MOCK_MODE=true uvicorn api:app --host 0.0.0.0 --port 8000 &

# 3. Console
cd ../../webui
pip install -r requirements.txt
ORCHESTRATOR_URL=http://localhost:8000 python3 app.py
```

## Configuration

Key environment variables (see [`.env.example`](../.env.example)):

| Variable | Purpose |
|----------|---------|
| `MOCK_MODE` | `true` short-circuits provisioning with fake outputs. |
| `RANGE_PROVIDER` | Default backend: `mock` \| `docker-local` \| `openstack` \| `aws`. |
| `NIDAVELLIR_API_KEY` | Bootstrap operator/admin API key for the orchestrator. |
| `ORCHESTRATOR_URL` / `ORCHESTRATOR_API_KEY` | Console → orchestrator address + key. |
| `SECRETS_ENCRYPTION_KEY` | Fernet key encrypting arena outputs / the BYO-model key at rest. |
| `NIDAVELLIR_ALLOW_SOURCE_BUILD` | Opt-in to building SUT workloads from source (off by default). |
| `WEBUI_USERNAME` / `WEBUI_PASSWORD` | Console login. |

## The console

- **Dashboard** — fleet KPIs, host capacity, source-split live activity.
- **Arenas** — running arenas (open / destroy) + archive.
- **Launch** — predefined · custom build · Vulhub import · paste spec · software-under-test.
- **Inventory** — scenario packs with the machines inside + topology preview.
- **Logs** — append-only audit, split by source (agent / human / system).
- **Agents** — BYO agents connected via the MCP gateway, by stance and arena.
- **Settings / Profile** — model connection (BYO key), preferences, identity.

## Built-in scenarios

| Scenario | Provider | Notes |
|----------|----------|-------|
| `container_web_pentest` | container | DVWA web target + Kali foothold on one segment. |
| `software_under_test` | container | OWASP Juice Shop stood up in a gated setup phase, then pentested. |
| `basic_pentest` | vm | Victim + Kali + monitor trio (legacy VM range). |
| `random_vulnhub` | container | Catalog-selected target + foothold. Import real CVE envs via `POST /scenarios/import/vulhub` ([Vulhub](https://github.com/vulhub/vulhub)). |

More detail: [`API.md`](API.md) · [`SCENARIOS.md`](SCENARIOS.md) · [`adr/`](adr/).
