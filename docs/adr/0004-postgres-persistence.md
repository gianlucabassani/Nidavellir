# ADR-0004: PostgreSQL persistence via SQLAlchemy + Alembic

- **Status:** Accepted
- **Date:** 2026-06-11 (accepted same day)
- **Deciders:** CyberGuard maintainers

## Context

Persistence today is a hand-rolled SQLite singleton (`database.py`): raw SQL
strings, a `try/except ALTER` "migration-lite" pattern, one `deployments`
table plus `api_keys`. That was right for a demo, but Phase 3 (multi-tenancy
& lifecycle) needs things SQLite + raw SQL make painful:

- **Concurrent writers.** API, Celery workers, and the upcoming TTL reaper
  all write. SQLite serializes writers per file; under real load
  (classrooms: N students × deploy at the same minute) lock contention and
  `database is locked` errors are a matter of time. The AWS hosting plan
  (Phase 7) puts API and workers on different hosts — a shared DB file no
  longer even exists.
- **Schema evolution.** Phase 3 adds users/orgs/quotas, lab TTLs, and an
  `events` table; Phase 5 adds scores/runs. The `ALTER`-in-`CREATE` trick
  doesn't compose past one column; we need real, ordered, reversible
  migrations.
- **Auditability.** Lab lifecycle needs an append-only `events` stream
  (state transitions, who did what) — both for the UI (SSE feed, P7-3) and
  for agent-run traces (Phase 5).
- **State integrity.** Status strings are scattered literals today
  (`"pending"`, `"deploying"`, …, `"error_destroying"`); illegal transitions
  (e.g. `destroyed → active`) are not prevented anywhere.

Constraints: the stack must stay demoable on a laptop with zero external
services (`make check` runs with no daemon today — keep that), and the
mock-mode demo path must not grow a hard Postgres dependency.

## Decision

We will:

1. **Adopt SQLAlchemy (2.x, typed ORM) as the data layer** behind the same
   `Database` facade the app already uses — callers (`api.py`, `tasks.py`,
   `auth.py`) keep their current method-level API while the internals are
   replaced.
2. **Target PostgreSQL in deployed environments** (docker-compose service
   now; RDS in Phase 7), configured via `DATABASE_URL`.
3. **Keep SQLite as the zero-dependency fallback** (default
   `DATABASE_URL=sqlite:///…`) so dev, tests, and the mock demo still run
   with no extra service. SQLAlchemy makes the dual-backend cost ~zero as
   long as we avoid Postgres-only column types in core tables.
4. **Manage schema with Alembic** from day one: an initial baseline
   migration capturing today's schema (incl. the `provider` column), then
   one migration per change. The `try/except ALTER` pattern is retired.
5. **Make lab status an explicit state machine**: a `LabStatus` enum and a
   single `transition(lab, new_state)` helper that enforces the legal graph
   (`pending → deploying → active → destroying → destroyed`, failure edges
   from every live state, `error_destroying` retryable to `destroying`).
   Illegal transitions raise; nothing else writes `status`.
6. **Add an `events` table** (id, lab_id, ts, actor, type, payload JSON),
   appended on every transition and admin action. It is the source for the
   UI live feed (P7-3) and the audit trail required by the agent gateway
   (Phase 5).

## Alternatives considered

- **Stay on SQLite (+ WAL mode).** Survives a single-host deployment, but
  dies on the Phase-7 topology (API and workers on separate hosts) and
  still leaves raw-SQL migrations. Postponing the move only grows the
  migration surface.
- **Raw SQL on psycopg directly.** Avoids the ORM dependency but keeps
  hand-written migrations and per-backend SQL dialects (we need SQLite for
  tests regardless). Alembic effectively requires SQLAlchemy anyway.
- **Heavier options (Django ORM, async ORMs).** Django drags a framework;
  async ORMs (SQLModel/async SQLAlchemy) buy nothing here — DB work happens
  in Celery workers and short FastAPI handlers, and sync SQLAlchemy keeps
  the test story simple.

## Consequences

- Positive: real migrations; concurrent writers stop being a time bomb;
  one enforced status graph (fixes the class of bugs behind audit #13 and
  the "stuck pending forever" failure mode at the data layer); the events
  stream unlocks SSE UI updates and agent audit trails.
- Negative / cost: two new dependencies (SQLAlchemy, Alembic) plus a
  Postgres container in compose; contributors must learn the migration
  workflow (`alembic revision --autogenerate` + review); dual-backend
  discipline (no Postgres-only types in core tables).
- Follow-ups: P2-2 (users/orgs/RBAC) builds on these models; P2-3 (TTL
  reaper) consumes the state machine; P7-3 (SSE) consumes `events`;
  Phase 7 swaps `DATABASE_URL` to RDS with no code change.

## Migration plan (implementation order)

1. Introduce SQLAlchemy models + engine/session plumbing behind `Database`;
   port methods 1:1; suite must stay green on SQLite.
2. Alembic baseline migration == current schema; CI runs
   `alembic upgrade head` against a scratch DB.
3. Add `LabStatus` enum + `transition()`; route all status writes through it.
4. Add `events` table + append hooks.
5. Add Postgres to docker-compose (prod profile) and CI matrix; SQLite
   remains the default for `make check`.
