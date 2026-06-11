# Architecture Decision Records (ADRs)

This directory captures significant architectural decisions for CyberGuard using
the lightweight [ADR](https://adr.github.io/) format.

## Why

An ADR records *what* was decided, *why*, and *what was traded away* — so future
contributors understand the reasoning instead of re-litigating it.

## How to add one

1. Copy `0000-template.md` to `NNNN-short-title.md` (next number).
2. Fill in Context, Decision, Consequences.
3. Set status to `Proposed`, link it from your PR. Mark `Accepted` on merge.
4. Superseding a past decision? Set the old one's status to
   `Superseded by ADR-NNNN` rather than deleting it.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-record-current-architecture.md) | Record the current architecture as a baseline | Accepted |
| [0002](0002-api-authentication.md) | API-key authentication and WebUI operator login | Accepted |
| [0003](0003-provider-driver-interface.md) | Pluggable deployment providers behind a RangeProvider interface | Accepted |
| [0004](0004-postgres-persistence.md) | PostgreSQL persistence via SQLAlchemy + Alembic | Accepted |
