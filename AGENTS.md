# Agent continuity — Nidavellir

Before making material changes, read these sources in order:

1. `README.md` — reproducible local vulnerability research and BYO-agent evaluation.
2. `ROADMAP.md` — product/design detail and dated verification boundaries.
3. `TODO.md` — canonical delivery order, stable NV task IDs, dependencies and acceptance.
4. Relevant `docs/adr/` decisions — preserve existing architecture boundaries.
5. `Makefile` targets (`make help`) for quick commands.
6. `git log` — when the sources above are silent or disagree with current code.

Dynamic N-node Docker arenas, stance-scoped MCP gateways and HTTP transaction replay
are implemented. NV-01–08 and NV-10 are complete: reproducible verification, target
reset, confined PoC execution, durable budgets/stop, scoped access, independent
validation, durable paired evaluations, a two-class calibration library and encrypted
record recovery. NV-09 completed its harness-agnostic BYO-agent workflow proof on
2026-10-05: direct opencode + deepseek-v4.1-flash MCP runs and a paired regression are
reproducible with `make verify-nv09-live`. Docker-local is the implementation focus;
OpenStack/AWS/libvirt drivers do not establish live provider support.

## Stack / gotchas

- Stack: Python, FastAPI, Celery, MCP, Docker, OpenStack, AWS.
- Provider abstraction (ADR-0003): `mock`, `docker-local`, `libvirt`,
  `openstack` — per-request provider selection, per-arena workspace isolation.
- PostgreSQL + SQLAlchemy + Alembic (ADR-0004), explicit lab state machine,
  append-only `events` audit table, TTL/stuck reaper.
- `MOCK_MODE` makes the full flow demoable/testable without cloud cost —
  use it before reaching for real OpenStack/AWS provisioning.
- `make check` runs ruff + bandit + pytest; CI runs the suite on SQLite and
  Postgres — run it before claiming anything "done."
- Guiding principle: **correctness and security before features** — the
  platform turns input into real infrastructure and gives agents command
  execution inside it. Treat any shortcut here as a regression, not a detail.
- Review 2026-09-07: Ruff and source-only Bandit passed; 121 focused tests passed.
  Full host Python 3.14 tests stalled in TestClient. No main Compose stack was running;
  no live arena or PostgreSQL suite was verified. NV-01 restores the Python 3.11 gate
  and fixes Bandit's nested `venv` exclusion; the old 808-test gate is historical.
  On 2026-09-26 the full host 3.14 suite completed without a stall (cause unknown,
  unpinned host packages); `make release-check` remains the only authoritative gate.

## Coding agents

These instructions are harness-neutral: no specific coding client is required. Give an
agent a concrete, scoped task that references the exact ROADMAP/ADR item. The same
scope, architecture, verification and reporting requirements apply to every client.

## Reporting

After material changes, record in the commit message (or PR) the outcome, files,
verification, unresolved risks and next concrete step. Complete a checklist item only
when its acceptance is met; planning does not implement a product feature.
