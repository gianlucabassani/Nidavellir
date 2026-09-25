# Agent continuity — Nidavellir

Before making material changes, read these sources in order:

1. `README.md` — reproducible local vulnerability research and BYO-agent evaluation.
2. `ROADMAP.md` — product/design detail and dated verification boundaries.
3. `TODO.md` — canonical delivery order, stable NV task IDs, dependencies and acceptance.
4. `ISSUES.md` — open risks and verification gaps; do not re-close them silently.
5. Relevant `docs/adr/` decisions — preserve existing architecture boundaries.
6. Latest `docs/JOURNAL.md` entry, then `.lab.yaml` for quick commands.
7. `git log` — when the sources above are silent or disagree with current code.

Dynamic N-node Docker arenas, stance-scoped MCP gateways and HTTP transaction replay
are implemented. NV-01–07 are complete: reproducible verification, target reset,
confined PoC execution, durable budgets/stop, scoped access, independent authorization
validation and durable paired evaluations. A dependable challenge library (NV-08),
Bughunt integration and record recovery remain planned. Docker-local is the
implementation focus; OpenStack/AWS/libvirt drivers do not establish live provider
support.

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

## Shared knowledge base

`~/Documents/NOTES` (curated by the `dante` profile) is the reference CS/
CyberSec knowledge base — read for context (e.g. prior notes on a relevant
attack surface or tool) when useful. Never write there; that's dante's job.

## Coding delegation

`nidavellirManager` tracks state, TODOs, and roadmap sequencing. It does not
write implementation code itself — for actual coding work, spawn Claude Code
from a terminal rooted at `~/Projects/Nidavellir` with a concrete, scoped
task description referencing the exact ROADMAP/ADR item.

## Reporting

After material changes, append a dated `docs/JOURNAL.md` entry with outcome, files,
verification, unresolved risks and next concrete step. Complete a checklist item only
when its acceptance is met; planning does not implement a product feature.

Use the `project-status-report` skill for scheduled/on-demand status reports.

**Proactive reporting rule:** when a concrete deliverable lands outside a
scheduled report slot (a roadmap item completed, an ADR decision made),
report it immediately in the same format rather than waiting for the next
scheduled run — this rule lives here, not only in a chat conversation.
