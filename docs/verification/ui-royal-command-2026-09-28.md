# Royal Command console verification — 2026-09-28

**Scope:** opt-in React console at `/console`; legacy Flask routes remain the
default. The gallery in [UI concepts](../assets/ui-concepts/README.md) uses
fixture data. The earlier visual system is preserved in the dated
[legacy manifest](../assets/legacy-console-reference/2026-09-28/MANIFEST.md).

## Code and browser checks

- Pinned `make release-check` on Python 3.11.14: Ruff and Bandit clean;
  SQLite 962 passed, four PostgreSQL-only skips, six integration deselections;
  PostgreSQL 966 passed, six integration deselections; migration/API/UI/gateway
  readiness smoke passed.
- Frontend `npm run check` and `npm run build`, packaged `docker compose build
  webui`, and `git diff --check` passed.
- Fixture-backed Chromium exercised Research source-bundle intake, HTTP
  capture/replay, isolated Browser, file upload/download with digest-mismatch
  rejection, PoC path prefill, findings, source diff/patch, Benchmark registry,
  arena setup/access, and shared views. Browser and Transfer tabs were checked
  at 1440, 390 and 320 px with no document overflow. These fixtures did not
  execute an actual Docker-local browser or transfer helper.

## Development Compose smoke

The existing SQLite file had all expected tables and indexes but lacked
`model_connections.base_url`, `deployments.effective_provider` and an Alembic
revision. It was compared with a clean revision `0009` database. A repair was
first validated on a disposable copy with SQLite integrity and authenticated
API reads. The running services were stopped; an online SQLite backup was
saved at `/tmp/nv-ui-development-backup-2026-09-28.db` (mode 0600). The two
nullable columns were added, the schema stamped `0009`, and integrity and both
pre-existing deployment records were confirmed before services restarted.

Chromium then loaded Research, Benchmark, Cyber Range, Targets and Settings
from the running Compose stack. Their BFF data requests returned HTTP 200.
Through the React Cyber Range form, a temporary arena
`ui-smoke-20260928` was launched, its arena/Browser/Transfer views loaded with
HTTP 200 data requests, and it was destroyed through the React confirmation
dialog. Its retained record reported `destroyed`. The stack uses `MOCK_MODE`;
the console now labels this simulation in the shell, launch form and arena.

## Open before default switch

- Complete Docker-local Research, Benchmark and Cyber Range browser journeys,
  including real Browser/Transfer helpers, reset and retained evidence.
- Resolve exact legacy route/action/deep-link and role/state parity from
  [the matrix](../UI_ROUTE_ACTION_MATRIX.md).
- Complete keyboard, focus, screen-reader and zoom/reflow review; observe three
  representative researchers; set performance budgets; run the fallback drill.

The mock arena smoke and the pinned backend gate are narrower than the
required UI cutover evidence. UI-R1 remains open in [ISSUES.md](../../ISSUES.md).
