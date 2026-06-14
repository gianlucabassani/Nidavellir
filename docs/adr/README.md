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
| [0002](0002-api-authentication.md) | API-key authentication and WebUI operator login | Accepted (roles → admin/operator/agent, 2026-06-13 pivot) |
| [0003](0003-provider-driver-interface.md) | Pluggable deployment providers behind a RangeProvider interface | Accepted |
| [0004](0004-postgres-persistence.md) | PostgreSQL persistence via SQLAlchemy + Alembic | Accepted |
| [0005](0005-mcp-agent-gateway.md) | MCP agent gateway protocol, stances & guardrails | Proposed (skeleton landed: lifecycle tools + auth + stance binding) |
| [0006](0006-aws-topology.md) | AWS topology — generic nodes[] module & egress lockdown | Proposed (driver + module landed; real apply needs creds) |

> **2026-06-13 pivot:** CyberGuard repositioned as an enterprise agent-testing
> arena (dynamic N-node topologies + bring-your-own agents via MCP as
> attacker/MITM/defender). The ADRs above remain accurate as historical
> records of their decisions; current product framing lives in
> [`../../.agent/proposals/VISION.md`] and `ROADMAP.md`. Older ADRs mention
> the prior school/classroom framing in their rationale — that is preserved as
> written, per the no-rewrite-of-accepted-ADRs convention.
