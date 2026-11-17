# Nidavellir

A self-hosted, contained cyber-range for authorized security research and for
evaluating security agents. Nidavellir starts reproducible targets in Docker,
gives a human or an agent a scoped place to work, records every action as
evidence, and has an independent referee check findings against the target.

You bring the agent. Nidavellir is the arena, the leash and the referee — it
does not ship an autonomous pentester.

## What it does

- **Target intake** — import a Git repository, container image or source bundle;
  the exact version under test is pinned and recorded.
- **Arenas** — N-node, N-segment Docker topologies with reset, interruption
  recovery and per-arena resource bounds.
- **Scoped agent access** — a stance-scoped MCP gateway exposes browser, HTTP
  request/replay, bounded file transfer and confined PoC tools to one arena only.
- **Durable budgets and stop** — action/time budgets are persisted and enforced
  server-side; an operator can stop a run at any point.
- **Independent validation** — deterministic validators re-check a claimed
  finding against the target; the agent's own claim is never the verdict.
- **Paired evaluations** — compare pinned agent builds on repeatable challenges,
  with event-derived scores and exports.
- **Retained evidence** — findings, HTTP transactions, traces and an append-only
  event history survive arena teardown; encrypted backup/restore of records.
- **Operator console** — a React console for launching, watching and reviewing
  work, including request comparison and source-candidate review.

Public and synthetic challenges are calibration material, not proof that an
agent can find unknown vulnerabilities.

## Architecture

```text
 Browser ──► Web console (Flask BFF: login, sessions, CSRF)
                    │
 Agent ──► MCP gateway (stance + arena scoped)
                    │
                    ▼
          Orchestrator API (FastAPI: authz, lifecycle, validation, scoring)
             │                 │                       │
        PostgreSQL        Redis + Celery         Provider driver
     (records, append-   (worker, beat:          (docker-local:
      only event log)     deploy/reset/reap)      arena containers)
```

All authorization lives in the API; the console and the gateway are thin
clients of it. A one-shot `migrate` service applies Alembic migrations before
the API starts, and on PostgreSQL the API refuses to start against a drifted schema.
Architecture decisions are recorded in [docs/adr/](docs/adr/README.md).

## Quickstart (development, mock mode)

Requires Docker with Compose v2.

```bash
git clone https://github.com/gianlucabassani/Nidavellir.git
cd Nidavellir
make dev            # docker-compose.yml + docker-compose.dev.yml, live reload
```

- Console: <http://localhost:5000> — login `admin` / `nidavellir`
- API: <http://localhost:8000>

`make dev-logs` tails the stack, `make dev-down` stops it. The dev stack runs in
`MOCK_MODE`: the full flow works without creating real target infrastructure.
The demo credentials are for a machine you control — never expose this stack.

For real Docker-local arenas, configuration and data handling see
[docs/OPERATIONS.md](docs/OPERATIONS.md); for a production install see
[DEPLOY.md](DEPLOY.md).

## Development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install-dev    # pinned runtime + dev dependencies
make check          # ruff + bandit + pytest (Python 3.11)
make release-check  # authoritative gate: clean Python 3.11, SQLite + PostgreSQL, in Docker
```

`make help` lists every target. See [CONTRIBUTING.md](CONTRIBUTING.md) for
branching, quality gates and ADRs.

Historical operator evidence is not included in this public checkout. For live
acceptance runs that write evidence, create `docs/verification/` locally first.
The UI-R4 gate also requires an operator-provided pinned reference inventory that
is not included. Research pre-registration requires a committed registration;
`docs/research/` is ignored by default, so deliberately review and explicitly
add a registration before running that workflow.

## Repository layout

```text
cyber-range/services/scenario-orchestrator   API, workers, providers, validators, migrations
cyber-range/services/agent-gateway           MCP gateway
cyber-range/webui                            Flask BFF + React operator console
cyber-range/fixtures                         calibration challenges
scenarios/                                   importable example scenarios
examples/agent-harness                       bring-your-own-agent example
compose/acceptance/                          isolated stacks for live acceptance gates
scripts/                                     deploy, backup, release and acceptance tooling
docs/                                        operations, API, MCP, security, ADRs
```

Root Compose files: `docker-compose.yml` (base stack), `docker-compose.dev.yml`
(development), `docker-compose.prod.yml` (production override) and
`docker-compose.verify.yml` (release-check harness).

## Status

Honest scope, as of the current release line:

- **Verified:** Docker-local provider with live acceptance runs for reset,
  confined PoC execution, budgets/stop, scoped access, independent validation,
  paired evaluations, a small calibration library, record recovery and a
  harness-agnostic BYO-agent workflow (reproducible with `make verify-*-live`).
- **Hardened:** fail-closed configuration outside mock mode, gunicorn-served
  console with session/CSP headers and login throttling, `/ready` readiness
  probe, bounded arena containers, deploy-time migrations.
- **Not supported:** OpenStack, AWS and libvirt drivers exist in code but have
  no live verification. Multi-tenant hosting and multi-agent red/blue are
  deferred.
- **Trust model:** the orchestrator and worker hold the Docker socket, i.e.
  root-equivalent on the host. Run Nidavellir on a dedicated host or VM, for
  trusted operators and authorized targets only. See
  [docs/SECURITY.md](docs/SECURITY.md).

The delivery order is in [TODO.md](TODO.md) and product scope in
[ROADMAP.md](ROADMAP.md).

## Documentation

- [Overview](docs/OVERVIEW.md) and [Vision](docs/VISION.md)
- [Operations](docs/OPERATIONS.md) — running the platform
- [Deployment](DEPLOY.md) — single-host production install, backup, rollback
- [API](docs/API.md) and [MCP](docs/MCP.md) — service and agent contracts
- [Scenarios](docs/SCENARIOS.md) — target and topology format
- [Security](docs/SECURITY.md) — trust boundaries and containment
- [Architecture decisions](docs/adr/README.md)

Documentation site: <https://gianlucabassani.github.io/Nidavellir>.

## Responsible use

Use Nidavellir only against systems you own or are explicitly authorized to
test. Arenas run real software with real vulnerabilities; keep them off
untrusted networks.

## License

GNU Affero General Public License v3.0 (AGPL-3.0) — see [LICENSE](LICENSE).
