# Agent continuity — Nidavellir

Before making material changes, read these sources in order:

1. `README.md` — reproducible local vulnerability research and BYO-agent evaluation.
2. `ROADMAP.md` — product/design detail and dated verification boundaries.
3. `TODO.md` — canonical delivery order, stable NV task IDs, dependencies and acceptance.
4. Relevant `docs/adr/` decisions — preserve existing architecture boundaries.
5. `Makefile` targets (`make help`) for quick commands.
6. `git log` — when the sources above are silent or disagree with current code.

Dynamic N-node Docker arenas, stance-scoped MCP gateways and HTTP transaction replay
are implemented; NV-01–10 are complete (see `TODO.md` for acceptance). Docker-local is
the implementation focus and the only provider with live verification. OpenStack, AWS
and libvirt drivers exist in code but do not establish live provider support.

## Workflow

One issue → one branch → one PR, as described in `CONTRIBUTING.md`. Branch from `main`
as `<type>/<issue#>-<slug>`, and close the issue from the PR (`Closes #N`). `main` is
protected: changes land only through a PR with green CI.

## Stack / gotchas

- Stack: Python 3.11, FastAPI, Celery, MCP, Docker, React operator console.
- Provider abstraction (ADR-0003): `mock`, `docker-local`, `libvirt`, `openstack`,
  with per-request provider selection and per-arena workspace isolation.
- PostgreSQL + SQLAlchemy + Alembic (ADR-0004), explicit lab state machine,
  append-only `events` audit table, TTL/stuck reaper.
- `MOCK_MODE` makes the full flow demoable and testable without creating real
  infrastructure. Use it before you reach for real provisioning.
- `make check` runs ruff, bandit, pytest and the readiness smoke on Python 3.11.
  `make release-check` (clean Python 3.11, SQLite + PostgreSQL in Docker) is the
  authoritative gate. Run it before you claim anything is done.
- The repository is public. The Guard workflow rejects secrets, absolute local paths
  and private material; never commit `.env`, keys, operator notes or run evidence.
- Guiding principle: **correctness and security before features**. The platform turns
  input into real infrastructure and gives agents command execution inside it. Treat
  any shortcut here as a regression, not a detail.

## Coding agents

These instructions are harness-neutral: no specific coding client is required. Give an
agent a concrete, scoped task that references the exact issue and ROADMAP/ADR item. The
same scope, architecture, verification and reporting requirements apply to every client.

## Reporting

After material changes, record in the commit message and PR the outcome, files,
verification, unresolved risks and next concrete step. Complete a checklist item only
when its acceptance is met; planning does not implement a product feature.
