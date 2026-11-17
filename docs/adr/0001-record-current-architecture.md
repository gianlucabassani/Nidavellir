# ADR-0001: Record the current architecture as a baseline

- **Status:** Accepted
- **Date:** 2026-06-10
- **Deciders:** Nidavellir maintainers

## Context

Nidavellir reached a working prototype (mock + OpenStack modes, Docker Compose
stack) without recorded design rationale. Before investing in the roadmap, we
record the as-built architecture so future ADRs have a baseline to amend.

## Decision

We document the current architecture as the starting point:

- **API** — FastAPI (`scenario-orchestrator/api.py`) exposes
  `deploy / destroy / status / deployments`. Stateless; persists to SQLite and
  dispatches async work to Celery.
- **Task queue** — Celery with a Redis broker/result backend. The worker runs
  the `Orchestrator` which shells out to OpenTofu (`tofu`).
- **Provisioning** — `orchestrator.py` copies the base Terraform templates into
  a per-lab workspace under `runs/<id>/`, writes a local-backend override for
  state isolation, and runs `init` + `apply`. A `MOCK_MODE` short-circuits this
  with synthetic outputs.
- **Persistence** — SQLite via a process-singleton `Database` class. One
  `deployments` table; `outputs` stored as a JSON string.
- **WebUI** — Flask app polling the API every 5s; Cytoscape topology view.
- **Packaging** — One Dockerfile for the orchestrator (shared by API + worker),
  one for the WebUI; `docker-compose.yml` wires redis + orchestrator + worker +
  webui.

## Alternatives considered

- *Synchronous provisioning in the API process* — rejected; `tofu apply` takes
  minutes and would block/timeout HTTP requests.
- *Terraform Cloud / remote state backend* — deferred; local per-workspace state
  is simpler for a single-node prototype.

## Consequences

- Positive: clear, decoupled components; mock mode enables fast dev/test.
- Negative / known debt (tracked in [SECURITY.md](../SECURITY.md) and the
  [ROADMAP](../../ROADMAP.md)): no auth, SQLite-only, path-resolution bugs in
  the Docker production path, no tests at baseline, no lab lifecycle/TTL.
- Follow-ups: ADR-0002 will cover the authn/authz model; a later ADR will cover
  the datastore decision (stay on SQLite vs. move to PostgreSQL) once
  multi-tenancy requirements are firm.
