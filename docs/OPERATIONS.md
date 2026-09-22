# Setup & Operations

Detailed run/operate notes. For what Nidavellir is and the roadmap, see the
[top-level README](../README.md).

## Run the stack (Docker, recommended)

Confined PoC execution requires the trusted image built by `make build-poc-runner`
(also built by the main Compose project). Workers refuse to pull an image during
PoC execution and create containers using the resolved local image ID. Keep the
worker and beat services running for execution and cleanup recovery. Configure
`SECRETS_ENCRYPTION_KEY` to protect persisted source and results.

`make verify-nv03-live` runs a dedicated PostgreSQL/Redis/API/worker/console/MCP
stack on ports 18003, 15003 and 19003. It tests target access, network/relay denial,
resource limits, interruption recovery, reset races and retained evidence, then
removes its own labelled resources. `make release-check` is the pinned Python 3.11
SQLite/PostgreSQL gate; `make verify-nv02-live` verifies reset compatibility.

Default admission limits are two jobs per arena and eight globally, configured by
`NIDAVELLIR_POC_MAX_ARENA_JOBS` and `NIDAVELLIR_POC_MAX_GLOBAL_JOBS`. Failed cleanup
retains its slot and is retried by the reaper. These per-job limits do not implement
NV-04's planned aggregate engagement budgets. Docker containers share the host
kernel; this feature is for local research, not VM-grade hostile multitenancy.

The dev stack runs everything — orchestrator, worker, Redis, console — in Docker,
with **mock mode pinned** and live source reload. No `.env` required.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# Console: http://localhost:5000   (login: admin / nidavellir)
# API:     http://localhost:8000   (header: X-API-Key: dev-insecure-key)
docker compose -f docker-compose.yml -f docker-compose.dev.yml down   # stop
```

`make check` runs the fast host gate (ruff + source-only Bandit + hermetic pytest +
readiness smoke) and requires Python 3.11. The reproducible clean-checkout release gate is:

```bash
make release-check
```

It builds a clean `python:3.11.14-slim-bookworm` verifier from
`requirements-lock.txt`, runs lint/security,
the SQLite suite and migration/API/UI/MCP readiness smoke, then repeats the test
suite against a disposable PostgreSQL 16 service. Live Docker-provider tests and
the OpenTofu integration test are marked `integration` and explicitly excluded;
run them separately with `make test-integration` on a suitably provisioned host.

NV-02 has a separate destructive-to-its-own-project live acceptance gate:

```bash
make verify-nv02-live
```

It uses `docker-compose.nv02.yml`, host ports 18000/15000, disposable PostgreSQL
and named volumes, and a synthetic local HTTP fixture. It deploys and mutates the
fixture, resets it twice from an immutable image identity, checks retained evidence,
kills the dedicated worker during another deployment, withholds the worker from a
queued teardown, verifies reaper cleanup for both interruption paths, and then removes
only the isolated `nidavellir-nv02` project. It never prunes Docker or
touches arenas from another project. The Docker socket is mounted only into the
dedicated orchestrator and worker because the live docker-local provider requires it.
A sanitized passing record is retained in
[`verification/nv02-live-2026-09-21.json`](verification/nv02-live-2026-09-21.json).

## Deployment modes

The provider is chosen per request or by the worker's environment:

| Mode | Set | Result |
|------|-----|--------|
| **Mock** | `MOCK_MODE=true` | Fake outputs, instant — demoable with no infrastructure. |
| **Container** | `MOCK_MODE=false`, `RANGE_PROVIDER=docker-local`, mount the Docker socket | Real per-arena container topologies on the local daemon (seconds, zero cloud cost). |
| **Local VMs (libvirt)** | `MOCK_MODE=false`, `RANGE_PROVIDER=libvirt` + libvirtd/KVM in the worker | Real per-arena **VMs on the local host** (KVM) via the `nodes[]` libvirt OpenTofu module — vm-class arenas with no cloud account. Prereqs below. |
| **OpenStack / AWS** | `MOCK_MODE=false` + provider credentials | Real VMs via the generic `nodes[]` Terraform/OpenTofu modules. |

> **Local VMs (libvirt) — status & prereqs.** The `libvirt` provider compiles a
> vm-class scenario to the `terraform-libvirt` module (one isolated libvirt network
> per segment → no egress by construction; one domain per node) and is
> schema-validated against `dmacvicar/libvirt` 0.7.6. Going live needs, in the
> worker: **qemu-kvm + libvirtd** (running, with `/dev/kvm` passed into the worker
> and the libvirt group), the **terraform-provider-libvirt** plugin, and a base
> cloud image (`LIBVIRT_BASE_IMAGE`). Not yet implemented (parity with the
> OpenStack/AWS VM drivers): `exec_in_node` (agent commands — needs SSH/guest-agent)
> and setup-egress toggling. So libvirt arenas currently **deploy/destroy** but are
> not yet agent-drivable. Design + roadmap: `.agent/research/local-vm-provider-qemu.md`.

Egress containment is **default-on** for locked arenas (a node cannot reach the
internet); opt out per scenario with `requires.egress: open`. See
[`SECURITY.md`](SECURITY.md).

## Run the services manually (without Docker)

Four processes — Redis, the Celery worker, the FastAPI orchestrator, the Flask console:

```bash
# 0. Prereqs: Python 3.11 (pinned in .python-version), Redis,
#    OpenTofu/Terraform only for VM providers
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

- **Home** — live engagements, findings awaiting a verdict, failed runs and
  containment warnings, provider/capacity health, and source-split activity.
- **Engagements** — running and archived engagements, plus **New engagement**:
  purpose · source · participants · time box, then the builder for predefined,
  custom, generated, Vulhub, Git, OCI, or local-bundle paths.
- **Evaluations** — reserved for the repeated-trial workbench (E1–E5); the route
  exists, its durable records do not yet.
- **Library** — Challenges (scenario packs with machines + topology preview);
  Targets and Agents are reserved for the target and agent-build registries.
- **Activity** — cross-engagement Findings and Evidence indexes, connected BYO
  agents by stance and arena, and the append-only audit trail split by source.
- **Administration** — settings and model connection (BYO key); providers and
  security are reserved destinations.

Opening an engagement gives the **workspace**: Overview · Live · Target ·
Findings · Evidence · Changes · Agent · Trace · Score · Infrastructure, with only
the applicable tabs shown and the active tab in the URL (`#findings` deep-links).
Live state, audit events, agent actions, findings, and monitor signals stream over
SSE. A destroyed arena stays open as a read-only record: no live actions, but its
findings, evidence, score, and trace remain reviewable.

## Connect your agent & review the engagement

Open an active engagement, go to the **Agent** tab, and use the **Agent positioning** card to authorize a
bring-your-own agent (attacker / MITM / defender) — enter your **agent key's name**
(from `auth.py create-key <name> agent`), pick a stance, and Authorize. The card's
recipe gives a one-line `claude mcp add --transport http nidavellir-arena <gateway>`
and a downloadable `.mcp.json` — no hand-written config. Then tell your agent to work
the arena (pass the `arena_id`); every tool call streams into the **Live** tab,
where you can Pause or Revoke.

The **Findings** tab lists what the agent submitted plus any operator-entered
findings. For each, **confirm** or **refute** it — an operator *confirmed* is
authoritative and counts toward the score (it flips the `verified_exploit` milestone),
which closes the gap for real web vulns a deterministic validator can't auto-prove.
**Benchmark** arenas show the scored manifest/challenges; **discovery / SUT** arenas
drop the gamified scoring and show findings + crash-oracle signals + your verdicts.

## Built-in scenarios

| Scenario | Provider | Notes |
|----------|----------|-------|
| `container_web_pentest` | container | DVWA web target + Kali foothold on one segment. |
| `software_under_test` | container | OWASP Juice Shop stood up in a gated setup phase, then pentested. |
| `basic_pentest` | vm | Victim + Kali + monitor trio (legacy VM range). |
| `random_vulnhub` | container | Catalog-selected target + foothold. Import real CVE envs via `POST /scenarios/import/vulhub` ([Vulhub](https://github.com/vulhub/vulhub)). |

More detail: [`API.md`](API.md) · [`SCENARIOS.md`](SCENARIOS.md) · [`adr/`](adr/).
