<p align="center">
  <img src="docs/assets/logo.svg" alt="Nidavellir — Enterprise Cyber Arena" width="620">
</p>

<p align="center">
  <b>An enterprise cyber arena for testing skills in dynamic environments — and, above all, for testing AI agents.</b><br>
  Provision arbitrary multi-machine vulnerable topologies on demand and expose them, through
  <b>MCP gateways</b>, to bring-your-own agents placed as <b>attacker</b>, <b>MITM</b>, or <b>defender</b>.
</p>

<p align="center">
  <a href="https://gianlucabassani.github.io/Nidavellir"><strong>Explore the Live Website & Interactive Docs »</strong></a>
</p>

<p align="center">
  <a href="https://gianlucabassani.github.io/Nidavellir"><img src="https://img.shields.io/badge/website-live-F5A524"></a>
  <img src="https://img.shields.io/badge/status-active_development-F5A524">
  <img src="https://img.shields.io/badge/stack-Python_·_FastAPI_·_Celery_·_MCP-3D9BFF">
  <img src="https://img.shields.io/badge/providers-docker--local_·_OpenStack_·_AWS-34D399">
  <img src="https://img.shields.io/badge/license-MIT-8A93A8">
</p>

---

Humans (operators) author and run engagements; **the AI is the system under test**. Every agent
is **bring-your-own** — connected via MCP under the operator's own key and model — and every
action flows through a gateway that enforces **scope**, applies **guardrails**, meters **per-key
budgets**, and writes an **append-only audit trace**. The whole stack runs on a laptop (Docker),
on OpenStack, or on AWS.

> **AI-centered, never AI-required.** Built for testing AI agents and MCP-compliant throughout,
> but every arena stays fully drivable by a human pentester with no model in the loop.

## The console

<p align="center"><img src="docs/assets/dashboard.png" alt="Nidavellir dashboard — fleet, host capacity, live activity" width="900"></p>

A mission-control dashboard: live arenas, host capacity, and a source-split activity stream
(agent / human / system) at a glance. The **Inventory** shows every scenario pack with the
machines inside it and a live topology preview:

<p align="center"><img src="docs/assets/inventory.png" alt="Nidavellir inventory — scenario packs with machine line-ups + topology" width="900"></p>

The **Arena View** gives operators full live-control over active topologies:

<p align="center"><img src="docs/assets/arena.png" alt="Inside Arena View — instance control and network segments" width="900"></p>

## Three pillars

1. **Dynamic N-node topologies** (GOAD-inspired). A scenario is a provider-agnostic, data-defined
   topology — arbitrary `nodes[]` + network `segments[]`, not a frozen trio. One spec compiles to
   docker-local containers, OpenStack VMs, or AWS. Ships as **arena packs** with variants.
2. **Agent runtime via MCP gateways** *(the priority)*. A BYO agent connects only through a gateway
   that wires it into a running arena as **attacker** (offensive foothold, scored), **MITM**
   (in-path on a shared segment), or **defender** (blue: events, alerts, response) — with scope
   enforcement, guardrails, budgets, and traces. Multiple agents can share one arena (red-vs-blue).
3. **Zero-to-prompt scenario generation** (BYO key). An LLM turns a brief into a topology spec;
   Nidavellir **validates** it against the schema and **compiles** it — never auto-deploying
   unreviewed infra.

The data model scales to new arena *kinds* cheaply — AD labs, service meshes, CTF web apps,
LLM-app targets, and **software-under-test (SUT) arenas**: point Nidavellir at any open-source
project and have a BYO agent pentest it, white- or black-box, deeply monitored and scored.

## Quick start

No cloud account needed — the dev stack runs everything in Docker, mock mode pinned:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# Console: http://localhost:5000   (login: admin / nidavellir)
# API:     http://localhost:8000   (header: X-API-Key: dev-insecure-key)
```

To run **real container arenas** on the local Docker daemon, set `RANGE_PROVIDER=docker-local`
and `MOCK_MODE=false` on the worker (see `docker-compose.dev.yml`). For OpenStack/AWS, configure
the provider credentials and flip `MOCK_MODE=false`.

Import a ready-to-run target from [Vulhub](https://github.com/vulhub/vulhub) (container CVE
environments) in one call:

```bash
curl -sX POST localhost:8000/scenarios/import/vulhub -H "X-API-Key: dev-insecure-key" \
  -H 'Content-Type: application/json' -d '{"path":"log4j/CVE-2021-44228"}'
```

## Architecture

```
┌────────────┐   HTTP    ┌──────────────┐   tasks    ┌─────────────┐   provider   ┌──────────────┐
│  Console   │ ───────▶ │ Orchestrator │ ───────▶  │   Worker    │ ──────────▶ │ docker-local │
│  (Flask)   │ ◀─────── │ (FastAPI)    │ ◀── Redis │  (Celery)   │   drivers    │ OpenStack/AWS│
└────────────┘           └──────┬───────┘            └─────────────┘              └──────────────┘
       ▲                        │ append-only events · API-key auth · Fernet-at-rest
       │ MCP gateway            ▼
  BYO agent  ─────────▶  attacker / MITM / defender stances  ·  scope · guardrails · budgets · trace
```

- **Console** (Flask + Jinja) — fleet, launch, inventory, logs, agents, configurator, co-pilot.
- **Orchestrator** (FastAPI) — `/deploy`, `/scenarios`, `/exec`, scoring; API-key auth (ADR-0002),
  append-only `events` audit table, Fernet-encrypted outputs at rest.
- **Worker** (Celery + Redis) → **provider drivers** (`mock`, `docker-local`, `openstack`, `aws`).
- **MCP agent gateway** — the BYO-AI seam; stance-scoped toolset + guardrails + JSONL trace.

## Roadmap

The plan is sequenced around the three pillars on top of the shipped production substrate.
Full detail in [`ROADMAP.md`](ROADMAP.md).

| Phase | Focus | Status |
|------|-------|--------|
| **0** | Repositioning & hygiene | ✅ complete |
| **1** | Dynamic topology engine (GOAD-style) | 🟡 in progress — schema v3 ✅, docker-local compiler ✅, image map ✅, **Vulhub importer ✅**, arena packs/variants ◻ |
| **2** | **MCP agent gateway & stances** *(differentiator)* | 🟡 in progress — gateway ✅, attacker ✅, defender (partial), configurator/SUT setup ✅, **key↔arena binding ✅**, MITM ◻ |
| **3** | Zero-to-prompt scenario generation (BYO key) | ◻ planned |
| **4** | Scoring, eval & trace datasets | 🟡 manifest + findings ✅, crash/monitor oracle ◻ |
| **5** | Hardening & multi-provider hosting (AWS) | 🟡 AWS `nodes[]` module ✅ (no real apply yet), RBAC/workspaces/SSO ◻ |
| **6** | Observability & scale | ◻ planned |
| **7** | Operator/auditor console | ✅ redesigned (mission-control dark) — SSE live feed ◻ |

## Documentation

Visit the **[Nidavellir Live Website & Interactive Docs](https://gianlucabassani.github.io/Nidavellir)** to browse the codebase documentation in a clean, interactive single-page app.

Individual markdown documents:
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — detailed setup & operations
- [`docs/API.md`](docs/API.md) — orchestrator REST API
- [`docs/SCENARIOS.md`](docs/SCENARIOS.md) — the v3 scenario schema + Vulhub import
- [`docs/SECURITY.md`](docs/SECURITY.md) — threat model & containment
- [`docs/adr/`](docs/adr/) — architecture decision records
- [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`ROADMAP.md`](ROADMAP.md)

## License

MIT.
