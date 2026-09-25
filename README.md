<p align="center">
  <img src="docs/assets/logo.svg" alt="Nidavellir — Agentic Arena Forge" width="620">
</p>

<p align="center">
  <b>A GUI-driven arena for security work on real running systems.</b><br>
  One engine, two objectives: <b>discovery</b> — find and prove real vulnerabilities with
  reproducible setup and evidence-grade proof — and <b>evaluation</b> — measure and compare the
  agents that hunt them, on held-out challenges.
</p>

<p align="center">
  <a href="https://gianlucabassani.github.io/Nidavellir"><strong>Explore the Live Website & Interactive Docs »</strong></a>
</p>

<p align="center">
  <a href="https://gianlucabassani.github.io/Nidavellir"><img src="https://img.shields.io/badge/website-live-F5A524"></a>
  <img src="https://img.shields.io/badge/status-active_development-F5A524">
  <img src="https://img.shields.io/badge/stack-Python_·_FastAPI_·_Celery_·_MCP-3D9BFF">
  <img src="https://img.shields.io/badge/provider-docker--local_(live)-34D399">
  <img src="https://img.shields.io/badge/license-MIT-8A93A8">
</p>

---

The two objectives are duals of one substrate. In **discovery** the target is under test and the
participant — human or agent — is the instrument; the output is a vulnerability record: finding,
PoC, observed effect, affected identity, disclosure state. In **evaluation** the AI is under test
and Nidavellir is the environment, capability boundary, observer, referee, and comparison layer —
never the pentesting agent itself. They meet at one asset: **a challenge is a solved discovery
problem with its truth withheld**, which is why verified findings from real research are the only
honest source of held-out evaluation material.

Humans author and operate the work. Interactive agents connect through scoped MCP gateways;
persistent or external agents will use the same evidence/scoring boundary through generic drivers.
The mature execution path runs locally with Docker.

> **AI-centered, never AI-required.** Built for testing AI agents and MCP-compliant throughout,
> but every arena stays fully drivable by a human pentester with no model in the loop.

## The console

Every normal workflow is complete in the browser. The console presents and drives; orchestration,
persistence, validation, and scoring stay behind the API.

```text
Home            live engagements · findings awaiting review · attention · capacity
Engagements     active + archived runs · New engagement (purpose · source · participants · time box)
Evaluations     durable agent builds, suites and paired baseline/candidate comparisons
Library         Challenges · Targets · Agents
Activity        Findings · Evidence · Audit trail
Administration  Providers & capacity · Security · Settings
```

Opening an engagement gives a **contextual workspace** — Overview · Live · Target · Findings ·
Evidence · Changes · PoC · Agent · Trace · Score · Infrastructure — where only the applicable tabs render
and the active tab lives in the URL, so `#findings` is a shareable deep link. Setup is a phase of the
engagement rather than a permanent page block. Arena state, audit events, agent actions, findings,
and monitor signals stream over **SSE**, resuming exactly on reconnect. When an arena is destroyed
its engagement becomes a **read-only record**: no live actions and no stale claims about running
nodes, but findings, evidence, score, and trace stay reviewable — evidence outlives the
infrastructure it came from.

The **PoC** tab runs Python in disposable, resource-limited Docker helpers. Choose
one target for HTTP(S) through `nidavellir.request("/path")`, or leave the job
networkless. Explicitly selected transfer files are copied into `/workspace/input`;
write small result files under `/workspace/artifacts`. Output, artifact hashes,
cancellation and cleanup state remain available after teardown. Raw TCP/UDP and
runtime package installs are unsupported. See [confined execution](docs/API.md#confined-poc-execution).

## Three engine pillars

1. **Dynamic topologies and target intake.** A scenario is a provider-agnostic, data-defined
   topology — arbitrary `nodes[]` + network `segments[]`, not a frozen trio — compiled by driver
   (docker-local is the live path; VM and cloud drivers are deliberately deferred). Targets resolve
   to immutable identities: a Git object, a digest-pinned OCI image, a hashed source bundle, or a
   named package, so a result says exactly what was tested.
2. **Scoped participant runtime.** A human or a BYO agent enters a contained arena through an
   explicit stance — **attacker** (offensive foothold, scored), **MITM** (in-path on a shared
   segment), or **defender** (events, alerts, response) — with server-enforced key↔arena bindings,
   narrow capabilities, no egress by default, and an append-only trace. Reproducible single-agent
   runs are the current requirement; multi-agent red-vs-blue is deferred.
3. **Independent evidence and comparison.** Monitor signals, deterministic validators, hashed
   evidence artifacts, and structured scores decide what a run achieved — a reflected XSS counts
   only when JavaScript is observed executing in a real browser. Unknown is not refuted, and
   immutable identities plus replay are what make an agent-version comparison explainable.

An LLM can also turn a brief into a topology spec (bring your own key); Nidavellir **validates** it
against the schema and **compiles** it, never auto-deploying unreviewed infrastructure. The data
model scales to new arena *kinds* cheaply — AD labs, service meshes, CTF web apps, LLM-app targets,
and **software-under-test (SUT) arenas**: point Nidavellir at any open-source project and have a BYO
agent pentest it, white- or black-box, deeply monitored and scored.

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

- **Console** (Flask + Jinja) — engagements, workspace tabs, activity indexes, configurator, co-pilot;
  live state over SSE.
- **Orchestrator** (FastAPI) — `/deploy`, `/scenarios`, `/exec`, scoring; API-key auth (ADR-0002),
  append-only `events` audit table, Fernet-encrypted outputs at rest.
- **Worker** (Celery + Redis) → **provider drivers** (`mock`, `docker-local`, `openstack`, `aws`).
- **MCP agent gateway** — the BYO-AI seam; stance-scoped toolset + guardrails + JSONL trace.

## Roadmap

The provisioning→monitoring→validation→score→eval-export engine is shipped, and so is the console
product model that gives every function a home. What remains splits into a shared research runtime
that both objectives need, a **discovery lane** (patch-diff and variant hunting, fuzzing into the
existing crash oracle, binary/appliance/VM intake, campaigns and disclosure output), and an
**evaluation lane** (durable experiment records and paired build comparison). Full detail is in
[`ROADMAP.md`](ROADMAP.md). The canonical ordered checklist is
[`TODO.md`](TODO.md), updated 2026-09-24: reliable local runtime first, then independently
validated repeated experiments, followed by research breadth driven by selected targets.
NV-01 restored the pinned Python 3.11 SQLite/PostgreSQL release gate on 2026-09-16.
NV-02 completed the live target lifecycle/reset gate on 2026-09-21. NV-03 confined
PoC execution completed its release and live gates on 2026-09-22. NV-04 durable
budgets and stop controls completed their release and live gates on 2026-09-23.
NV-05 fixed-destination TCP forwards and principal-filtered capability discovery
completed the PostgreSQL, release and live gates on 2026-09-23. NV-06 independent
authorization validation completed its pinned release, isolated Docker live and
NV-02–05 regression gates on 2026-09-24. NV-07 durable paired experiments completed
their pinned release and isolated Docker live gates on 2026-09-25. NV-08's dependable
challenge library is next.

| Stage | Focus | Status |
|---|---|---|
| **Shipped engine** | Dynamic arenas, target intake, repo→service, monitoring, validators, scoring, eval export and replay | ✅ shipped |
| **Research session** | Change evidence, file transfer, browser, HTTP capture/replay, finding attachment, confined PoC, durable action/time stop controls and declared-service TCP forwards | 🟢 partially shipped |
| **Console architecture** | Engagements, Evaluations, Library, Activity, unified creation, contextual workspace and SSE | ✅ shipped |
| **Research-ready runtime** | NV-01–05 complete on Docker-local; unsupported model token/cost hard caps are explicit | ✅ complete |
| **Discovery lane** | Patch-diff & variant hunting, fuzzing + crash triage, binary/appliance/VM intake, campaigns & disclosure output | ◻ planned |
| **Evaluation workbench** | NV-06 independent authorization effect validation and NV-07 durable paired trials shipped; NV-08–10 challenge library, Bughunt proof and recovery remain | 🟢 partially shipped |
| **Held-out proof** | A real vulnerability found and proven on-platform; then a comparison over challenges drawn from that work | ◻ planned |
| **Deferred** | OAuth/multi-tenancy, live cloud/VM providers, purple-team, VNC and hosted-product concerns | ◻ deferred |

## Documentation

Visit the **[Nidavellir Live Website & Interactive Docs](https://gianlucabassani.github.io/Nidavellir)** to browse the codebase documentation in a clean, interactive single-page app.

Individual markdown documents:
- [`docs/VISION.md`](docs/VISION.md) — product purpose, scope and language
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — detailed setup & operations
- [`docs/API.md`](docs/API.md) — orchestrator REST API
- [`docs/SCENARIOS.md`](docs/SCENARIOS.md) — the v3 scenario schema + Vulhub import
- [`docs/SECURITY.md`](docs/SECURITY.md) — threat model & containment
- [`docs/adr/`](docs/adr/) — architecture decision records
- [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`ROADMAP.md`](ROADMAP.md)

## License

MIT.
