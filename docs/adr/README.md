# Architecture Decision Records (ADRs)

This directory captures significant architectural decisions for Nidavellir using
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
| [0005](0005-mcp-agent-gateway.md) | MCP agent gateway protocol, stances & guardrails | Accepted (gateway, stance tools, bindings, browser/file slices landed; guardrails extend in R1–R3) |
| [0006](0006-aws-topology.md) | AWS topology — generic nodes[] module & egress lockdown | Proposed/deferred (driver validates; no live apply) |
| [0007](0007-software-under-test-arenas.md) | Software-under-test arenas — provision/configure/monitor/score any OSS project | Accepted (provision→configure→monitor→score spine landed) |
| [0008](0008-repo-image-build-pipeline.md) | Repo → image build pipeline (deterministic-first, LLM-fallback) | Accepted (Dockerfile, verified synthesis, and package tiers landed) |
| [0009](0009-scoring-validators-monitor.md) | Monitoring, deterministic validators & structured scoring | Accepted |
| [0010](0010-eval-layer.md) | Eval records/export, reference harness, batch suite, and replay | Accepted |
| [0011](0011-research-sessions-change-intelligence.md) | Reproducible research sessions and change intelligence | Accepted |
| [0012](0012-gui-first-product-model.md) | GUI-first product model and console information architecture | Proposed |

> **Product framing:** the 2026-06-13 pivot established the bring-your-own-agent
> arena. The 2026-08-10 reorganization (ADR-0012) makes the GUI-driven
> Engagement/Evaluation model explicit. Accepted ADRs remain historical records
> of their decisions; current sequencing lives in `ROADMAP.md`. Older ADRs may
> retain superseded phase names in their rationale.
