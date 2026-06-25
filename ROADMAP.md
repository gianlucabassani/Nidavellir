# 🛡️ Nidavellir Roadmap

> The plan to take Nidavellir from a working lab launcher to an **enterprise
> cyber arena for testing skills in dynamic environments — and, above all, for
> testing AI agents**. It provisions arbitrary multi-machine vulnerable
> topologies and exposes them, through **MCP gateways**, to bring-your-own
> agents placed as **attacker / MITM / defender**.
>
> The authoritative product statement is [`.agent/proposals/VISION.md`]; this
> roadmap is the sequenced execution plan. It stays opinionated: **correctness
> and security before features**, because the platform turns input into real
> infrastructure and gives agents command execution inside it.

Reference points: **GOAD** (data-defined modular multi-machine labs, variants,
multi-provider) is the technical model for the topology engine. Separately, we
aim to match the **product-quality** bar of well-executed security products on
UI/UX and operator utility — but that is a quality bar only, *not* a scope or
technical model; the gateway and stances are designed on their own terms.

---

## 1. Where the project stands

**Production substrate already shipped (keep — re-framed, not redone):**

- Decoupled control plane: FastAPI ↔ Redis/Celery ↔ provider drivers.
- **Provider abstraction** (ADR-0003): `mock`, `docker-local` (container arenas,
  seconds to deploy, zero cloud cost), `openstack`; per-request provider
  selection; per-arena workspace isolation.
- API-key auth with roles (ADR-0002); input validation; CSRF + API rate limits.
- **PostgreSQL + SQLAlchemy + Alembic** (ADR-0004); explicit lab **state
  machine**; append-only **`events` audit table**; **TTL/stuck reaper**.
- **Secrets hygiene**: log redaction + Fernet-encrypted outputs at rest.
- `MOCK_MODE` makes the whole flow demoable/testable with no cloud; `make check`
  (ruff + bandit + pytest) green; CI runs the suite on SQLite and Postgres.

**Two structural limits this roadmap removes:**

1. The deploy path is still tied to a **frozen 3-VM OpenStack template** (victim
   + Kali + Wazuh) inherited from a school OpenStack (the `EDU-ITS` defaults).
   Scenarios must become arbitrary **N-node topologies** compiled per provider.
2. The only first-class consumer is a human in a browser. The **agent runtime**
   (MCP gateways, attacker/MITM/defender stances) — the core of the product —
   does not exist yet.

---

## 2. Audit punch list (June 2026)

Severity: 🔴 High · 🟠 Medium · 🟡 Low. These were the original correctness/
security findings; all the load-bearing ones are fixed. Kept for the record.

| # | Sev | Issue | Where | Status |
|---|-----|-------|-------|--------|
| 1 | 🔴 | **Docker production path bug** — `orchestrator.py` recomputed paths from `__file__`, ignoring `config.py`/`RUNS_DIR`. | `orchestrator.py`, `config.py` | Fixed ✅ |
| 2 | 🔴 | **No authn/authz.** Any caller could deploy/list/destroy. | `api.py` | Fixed ✅ (API keys + roles — ADR-0002; ownership lands in Phase 5) |
| 3 | 🔴 | **Hardcoded Flask secret + `debug=True`** (RCE). | `webui/app.py` | Fixed ✅ (env-driven) |
| 4 | 🟠 | **No input validation** on `scenario`/`instance_id`. | `api.py` | Fixed ✅ (Pydantic + scenario registry) |
| 5 | 🟠 | **JS syntax error** broke all dashboard JS. | `dashboard.js` | Fixed ✅ |
| 6 | 🟠 | **Topology IPs never render** (wrong output keys). | `dashboard.js` vs `outputs.tf` | Fixed ✅ |
| 7 | 🟠 | **No tests, no CI.** | repo-wide | Fixed ✅ |
| 8 | 🟠 | **Bare `except:`** swallowed errors. | `api.py`, `orchestrator.py` | Fixed ✅ (bandit gate blocking) |
| 9 | 🟠 | **No arena TTL / reaper** → cost + quota leak. | orchestrator/worker | Fixed ✅ (Phase-3 reaper) |
| 10| 🟠 | **`random_vulnhub` not wired** to the importer. | `vulnhub-importer/*` | Vulhub-container importer landed ✅ (2026-06-24, `vulhub_import.py` + `POST /scenarios/import/vulhub`); VulnHub-VM converter still planned |
| 11| 🟠 | **CSRF** absent on WebUI POSTs. | `webui/app.py` | Fixed ✅ (+ API rate limiting) |
| 12| 🟡 | **CLI dead code.** | `cli.py` | Fixed ✅ (deleted) |
| 13| 🟡 | **`update_deployment` truthiness bug**; no migrations. | `database.py` | Fixed ✅ (ADR-0004) |
| 14| 🟡 | **Secrets in plaintext** in DB `outputs` and logs. | `database.py` | Fixed ✅ (redaction + Fernet at rest) |

See [`docs/SECURITY.md`](docs/SECURITY.md) for the threat model.

### 2.1 Security hardening pass (June 2026 — review + SUT-wizard follow-up)

A second audit (logic errors plus a focused **authorization** and **SSRF** review)
after the SUT launch wizard landed. Load-bearing logic / SSRF / data-leak findings
are fixed; three **structural authorization** findings are deferred to their phases
(they need a model change, not a patch) and tracked here so they aren't lost.

**Fixed ✅**

| # | Sev | Issue | Where | Fix |
|---|-----|-------|-------|-----|
| H1 | 🔴 | Setup session derived from the newest **500** events → a busy arena silently "closes" it → egress reaper never revokes + step-budget bypass | `setup_phase.py`, `api.py`, `tasks.py` | Fetch only setup-lifecycle event **types** within a 3×budget window (`list_events(types=)`) |
| H2 | 🔴 | `set_node_egress` close swallowed real Docker `APIError` → reported `closed` while the victim kept full internet egress | `providers/docker_local.py` | Verify the node is off the egress bridge before reporting `closed`; fail otherwise |
| H3 | 🔴 | AWS provider emitted no `node_<name>_name` → WebUI rendered **zero nodes** | `providers/aws.py` | Emit `node_<name>_name` |
| H4 | 🔴 | **SSRF**: a user `repo` URL (SUT wizard / white-box / build) could target `169.254.169.254`, loopback, or RFC1918; the clone helper has full egress | `netguard.py` (new), `api.py`, `providers/docker_local.py` | `assert_public_host()` blocks metadata/link-local/loopback/private/CGNAT — at request-time (literal) and provider-time (resolved) |
| H5 | 🔴 | `/events` leaked `matched_vuln_id` (hidden-manifest match) to **agent**-role callers → defeats the benchmark | `api.py` | Strip ground truth from `finding` events for non-operators |
| M1 | 🟠 | `setup/propose` had no budget check; cross-session proposal approval | `api.py`, `setup_phase.py` | 429 on exhausted budget; reject a proposal from a different session (`session_id` carried) |
| M2 | 🟠 | Gateway charged the step budget **before** exec; resolve-failure left no failure trace | `agent-gateway/gateway/tools.py` | Consume budget only after a successful action; resolve the foothold inside the traced `try` |
| M3 | 🟠 | `Requires.egress/mirror` dropped on validation; webui `poll_status` swallowed non-200; `_catalog` `KeyError`; co-pilot chat-history corruption | `scenario_spec.py`, `webui/app.py`, `webui/static/js/app.js` | Modeled the fields; normalized status; `.get`; error replies kept out of history |
| D1 | 🔴 | **No key↔arena/session binding** — any valid `agent` key could drive *any* arena (`/exec`, `/findings`, setup `propose`/`run`/`finish`); the gateway stance gate was client-side only, so a direct REST call bypassed foothold-scope. | `bindings.py` (new), `api.py` | Server-enforced **per-arena key↔arena binding**: an `agent` key may drive an arena only with an active `agent_binding`, whose **stance** scopes the capability orchestrator-side (attacker → foothold-only exec; configurator → setup only). Granted auto-on-self-deploy / by operator (`POST /arenas/{id}/bindings`) / named at `setup/start` (revoked at finish). Operators bypass. → ADR-0005 guardrail #6. |

**Deferred — security backlog (needs a design change; tracked to a phase):**

| # | Sev | Issue | Target |
|---|-----|-------|--------|
| D2 | 🟠 | **WebUI collapses all operators into one orchestrator identity** (shared `ORCHESTRATOR_API_KEY`); `principal.name` (the model-connection key) isn't unique → operators share one BYO model credential. | **Phase 5** — ownership/RBAC + multi-tenant workspaces + SSO; per-operator orchestrator identity. |
| D3 | 🟠 | **Bootstrap key role defaults to `admin`**; `dev-insecure-key` is the default WebUI↔orchestrator key (a log warning is the only guard). | **Phase 5 hardening** — refuse a privileged role on the well-known dev key; default bootstrap to least privilege. Quick win; can land earlier. |

Full detail + live verification are in `.agent/STATE.md` (2026-06-21 entries).

---

## 3. Phased plan

Effort: S ≈ days, M ≈ 1–2 weeks, L ≈ 3–5 weeks for one dev.

> **Re-sequenced 2026-06-13** around the enterprise-arena pivot. The old
> phases (provider abstraction, multi-tenancy/lifecycle, scenario packages,
> scoring) shipped as the *substrate*; the roadmap now drives the three product
> pillars — topology engine, MCP agent gateway, prompt-to-scenario generation —
> on top of it.

> **Standing principle (all phases): AI-centered, never AI-required.** Nidavellir
> is built for testing AI agents and is MCP/agent-compliant throughout, but every
> arena must remain fully usable by a **human attacker against a static vulnerable
> target, with no model in the loop** (browser / SSH / console access to the
> attacker node + manual finding submission). The MCP gateway and agent stances are
> an *additional* way in, never the only one.

### Arena archetypes & the software-under-test (SUT) arena

The data-defined model (Phase 1) exists so that **new arena *kinds* are cheap**: a
scenario is config, not code, so AD labs, service meshes, CTF-style web apps, and
LLM-app targets are all one engine with different packs. The flagship next
archetype — and the one that most exercises this extensibility — is the
**software-under-test (SUT) arena**: point Nidavellir at *any* open-source project
and have a bring-your-own agent pentest it, **white- or black-box**, with the
service stood up on the victim node, deeply monitored, and scored.

It is **not a new engine** — it composes the existing topology compiler, egress
containment + package mirror, MCP gateway/stances, and the events/scoring spine.
It needs four small, reusable capabilities, slotted into the phases below:

1. **Service provisioner** (Phase 1), **packaged-first** — a node's workload is a
   `service:` block: an *image*/container (preferred), a *package*, or *source*
   (git repo + ref + build), pinned for reproducibility. **Black-box** prefers an
   existing, user-approved image and builds from source only for gaps (avoids
   version mismatch); **white-box** requires the source, configured per the
   project's own instructions, with the agent reading the source while it tests
   dynamically from the attacker node. (Distinct from catalog/VulnHub expansion.)
2. **Optional AI-assisted setup, gated** (Phase 2) — standing an arbitrary service
   up often needs configuration. The operator chooses, per arena, how: operator-
   scripted, **human-in-the-loop** (the agent proposes setup steps; the operator
   approves), or **autonomous** — a short-lived, **opt-in** *configurator* role
   with write/config tools on the victim node, dropped before the engagement. The
   consent gate is load-bearing: write/config access is never granted silently.
3. **Deep monitoring + crash oracle** (Phase 4) — a sidecar around the service
   captures logs, crashes/panics, sanitizer aborts, unhandled 5xx, and resource
   exhaustion into `events`/the defender feed. A crash or sanitizer abort is a
   **first-class evidence signal**, so a target with *no pre-known manifest* can
   still be scored ("the agent made it fall over").
4. **Scoring for open-ended targets** (Phase 4) — *discovery mode* (evidence +
   self-reported findings; operator triages) or *benchmark mode* (pin a version
   with known CVEs + a manifest → score CVE-rediscovery per model).

Operators drive all of this through an **arena wizard** (Phase 3 → console in
Phase 7): white vs black box, the setup/configurator choice + consent, target ref,
exposed ports, monitoring level, scoring mode, budgets → a validated pack via the
existing validator/compiler. Designed for scale: container-first, version-pinned,
TTL-reaped, and runnable in parallel like every other arena. The scope boundary
holds — when the model configures the service it is still **bring-your-own AI under
the operator's key**, exercising a gated capability Nidavellir provides; Nidavellir
ships the provisioner, sandbox, monitor, and consent gate, not the AI. Decision
record: **ADR-0007**.

### Classic-range authoring & import (operator track)

The pivot put most of the build behind the **MCP gateway** (Phase 2). The
"classic cyber-range" surface — *authoring, importing and visualizing the
target topology itself* — lagged: the schema/validator/compiler are real, but
the front-half (getting a topology **in**, seeing it, and persisting it) is thin.
This is an operator-facing track that **composes the existing engine**, sequenced
across the phases below in four steps that build on each other:

- **A — Authoring & import seam (Phase 1).** A scenario today is discovered only
  by dropping a YAML file on the orchestrator's disk; custom/SUT arenas compile a
  spec but **deploy it inline and never persist a reusable pack**. Add a
  first-class **import/registry write** path: `POST /scenarios` validates a v3
  spec (JSON/YAML) via the existing `ScenarioSpec` and saves it as a pack under a
  writable, mounted dir (`DATA_DIR/scenarios/`) alongside the built-in templates;
  `DELETE /scenarios/{id}` removes imported packs (built-ins are read-only). Same
  step generalizes the **custom builder to multiple attacker machines** (the
  schema already allows N entrypoints + N attacker bindings — only the builder/UI
  hard-code one). This seam is also the landing zone for steps C and D. → **P1-7**.
- **B — Topology visualization (Phase 7, pulled forward).** Render a scenario's
  topology **before** it is deployed (from the spec: nodes + segments + agent
  stances), not only post-deploy from provider outputs. A modern, minimal
  segment-grouped graph, reused for the launch preview, the import preview, the
  scenarios page, and (restyled) the live arena. → **P7-9**.
- **C — Community import → v3 pack (Phase 1).** A deterministic converter from
  public sources that lands a ready-to-run pack in the registry (step A). Targets
  **both** **Vulhub** (container CVE environments — native to docker-local; **DONE**
  2026-06-24 — `vulhub_import.py` + `POST /scenarios/import/vulhub` + WebUI card)
  and **VulnHub** (full VM disks — VM providers; modernizes the orphaned legacy
  importer; **planned**). Complementary to SUT provisioning, not replaced by it.
  → **P1-5**.
- **D — Zero-to-prompt generation (Phase 3).** The LLM (BYO key) emits a v3 spec →
  validate → **preview (B)** → review-gate → **import (A)** → compile (existing).
  The capstone "generate JSON → parsed into docker/Terraform targets"; it depends
  on A + B existing first. → **P3-1/P3-2**.

> Note: `docs/tmp_basic_codebase_review.md` is a **stale** audit (its findings were
> addressed June 2026 — see §2.1); archive it. One finding remains open *by design*:
> custom/SUT arenas carry no vuln manifest, so findings don't score (discovery-mode;
> tracked to **P4-7**).

### 🟠 Phase 0 — Repositioning & hygiene · **S** *(complete)*

**Goal:** the whole project reads as the enterprise arena; the school/ITS
framing is gone from docs *and* code.

- [x] Rewrite vision/positioning/planning docs: VISION.md, ROADMAP, AGENT.md,
      README, proposals, backlog.
- [x] **Role rename (first code step):** `auth.py` `ROLES` instructor/student →
      **operator** (kept `admin`, `agent`); `tests/test_auth.py`, `docs/API.md`,
      ADR-0002 "superseded in part" note updated. (Legacy keys still authenticate.)
- [x] Neutralize the inherited OpenStack template: Italian descriptions → English;
      `EDU-ITS` default dropped; `basic_pentest`/"Mr. Robot" branding removed
      across the scenario YAMLs, Terraform, and WebUI. (Scenario *id* kept;
      the schema generalization is Phase 1.)

**Acceptance:** a terminology sweep (`instructor|student|classroom|EDU-ITS|…`)
returns only intentional historical/superseded notes; `make check` green (141
passed). **Phase 0 complete** apart from the legacy bootstrap script staying
Italian (cosmetic; replaced with the Phase-1 `nodes[]` module).

### 🔴 Phase 1 — Dynamic topology engine (GOAD-style) · **L**

**Goal:** a scenario is an arbitrary, data-defined N-node topology that one
codebase compiles to any provider — the frozen 3-VM template is gone.

Key work:
- **Scenario schema v3**: `scenarios/<slug>/scenario.yaml` with abstract
  `nodes[]` (name, role/kind, image, size, ports, provisioning) and network
  `segments[]`; Pydantic + published JSON Schema; loader/validator; `GET
  /api/v1/scenarios` registry.
- **Generic provider compiler**: `docker-local` first (per-arena network, one
  container per node, `for_each`-style fan-out), then a generic OpenStack
  `nodes[]` Terraform module (replacing the fixed template), then AWS in
  Phase 5. Per-provider **image map** (`kali` → container tag / Glance image /
  AMI).
- **Arena packs + variants** (GOAD model: full / light / mini); a first
  multi-node AD-style or service-mesh arena beyond the legacy 2–3 node ones.
- **Community importer / catalog expansion** (#10): a **deterministic auto-converter
  from public sources** → import → emit a v3 scenario pack + image registration. A
  **separate, still-needed track** that grows the library of known, ready-to-run
  targets — complementary to SUT provisioning, not replaced by it. **Vulhub
  (containers) DONE** (2026-06-24): `vulhub_import.py` converts a Vulhub Docker
  Compose env → v3 pack (image→image, build→gated `service.source`,
  ports/environment/command mapped; honest drops reported), via
  `POST /scenarios/import/vulhub` (fetch-by-path or pasted compose, `dry_run`
  preview) + a WebUI card, landing in the P1-7 registry; needed the new
  `Node.environment` field. **VulnHub (VM disks)** — planned (modernize the orphaned
  `vulnhub-importer/`; needs a VM provider + qemu).
- **SUT provisioning (software-under-test arenas), packaged-first:** a `service:`
  block on a node — an `image`/container (preferred), a `package`, or `source` (git
  repo + ref + build). **Black-box prefers an existing, user-approved image and
  builds from source only for gaps** (avoids version/build mismatch); **white-box
  requires the source**, configured per the project's own instructions, with the
  agent reading the source while it tests dynamically from the attacker node.
  Version-pinned; ship a first `software-under-test` pack. Separate from the
  VulnHub auto-converter / catalog expansion (P1-5). (Archetype above; ADR-0007.)

**Acceptance:** one scenario spec deploys an N-node arena on at least two
providers with no code change; adding a scenario = dropping a validated pack.

### 🟢 Phase 2 — MCP agent gateway & stances · **L** *(the differentiator)*

**Goal:** drop a bring-your-own agent into a running arena, via MCP, as
attacker / MITM / defender — fully scoped, budgeted, and traced.

Key work:
- **`services/agent-gateway/`** — an MCP server (streamable HTTP; stdio for dev)
  that is the *only* path an agent has into an arena. Lifecycle tools
  (`list_scenarios`, `deploy_arena`, `arena_status`, `get_briefing`,
  `destroy_arena`) proxy the REST API; the per-stance toolsets are the product.
- **Stances** (each a scoped MCP toolset + guardrails + trace):
  - **attacker** — `run_command` (SSH / `docker exec` on the foothold node),
    `upload/download`, `report_finding` (self-report a discovered known vuln);
  - **MITM** — in-path position on a shared segment: observe and manipulate
    traffic between arena nodes (sanitize / flag / block);
  - **defender** — `query_events` / `get_alerts` / `submit_detection`.
- **Guardrails (server-enforced):** provider-enforced **egress lockdown** (no
  internet from arena segments — verified by a CI containment test), best-effort
  scope screen, **per-arena key↔session binding** so an agent key can only act on
  its assigned arena and the orchestrator (not just the gateway) enforces stance/
  node-scope (§2.1 D1 — the current gate is gateway-side only), per-key
  **step/time/token budgets**, per-command timeout,
  operator **kill switch / pause** — **two-scope** (per-arena and per-workspace):
  a paused scope rejects new agent tool-calls and the worker stops enqueuing
  while an **in-flight command completes** (no half-state, nothing lost), with a
  `PAUSED` state surfaced and a clean resume.
- **Trace capture:** append-only JSONL per run + index in `events`; paired
  red/blue streams when stances run concurrently on one arena.
- **MOCK_MODE:** canned `run_command` responses per scenario so agent-loop
  tests stay free and deterministic.
- **Reference connectors** (thin, optional): an `examples/agent-harness/`
  Claude tool-use loop and a custom-model sample — wiring samples, not products.
- **Setup / configurator capability (SUT arenas):** an operator-gated, time-boxed
  role with write/config tools on the victim node to *bring a service up*
  (operator-scripted / human-in-the-loop / autonomous-opt-in), then dropped to the
  attacker stance for the engagement; plus **white-box source access** (the mounted
  repo) when the arena is white-box. The consent gate + HITL approval path are
  mandatory — never silently granted. (Archetype above; ADR-0007.)

**Acceptance:** a BYO agent connected over MCP completes a container arena
end-to-end with every action audited; a containment test proves arena nodes
cannot reach the internet; red and blue agents run concurrently on one arena
with paired traces. ADR-0005 (gateway protocol & guardrails).

### 🔵 Phase 3 — Zero-to-prompt scenario generation (BYO key) · **M** · _in progress (core + WebUI generator shipped 2026-06-25)_

**Goal:** an LLM turns a brief into a deployable arena, safely.

> **Status (2026-06-25):** the prompt→spec generator core is live — `POST
> /scenarios/generate` (operator-only) drafts a v3 spec with the operator's BYO
> model, validates it, and returns spec + topology **without deploying** (the
> review gate); a Launch "Generate" card drives it. The MCP path is the
> operator-keyed author→preview→import→deploy route — authoring stays an operator
> privilege, deliberately absent from the in-arena agent gateway. Remaining:
> Terraform/vm-target generation, a literal operator-tier `scaffold_scenario`
> tool + diff view, and the arena wizard (P3-3).

Key work:
- `range-authoring` surface: prompt → topology spec (Terraform/JSON) → **validate
  against the v3 schema** → compile via the provider abstraction → deploy.
- Operator supplies their own AI key/model; Nidavellir ships the schema +
  validator + compiler + sandbox only. **Never auto-deploy unreviewed infra** —
  generated specs are diffed/reviewed before apply.
- Exposed as an MCP authoring tool (`scaffold_scenario`) and in the WebUI.
- **Arena wizard (incl. SUT arenas):** a guided authoring flow — target source /
  image / package + ref, white vs black box, the setup/configurator choice +
  consent, exposed ports, monitoring level, scoring mode, budgets → a validated v3
  pack via the same validator/compiler. The configurator-consent is the
  load-bearing safety choice; nothing with write/config or autonomy is enabled
  without it. (Console surface in Phase 7; archetype above.)

**Acceptance:** a natural-language brief produces a schema-valid scenario pack
that deploys; invalid generations are rejected with actionable errors; nothing
deploys without an explicit review step.

### 🟣 Phase 4 — Scoring, eval & trace datasets · **M**

**Goal:** arenas double as reproducible benchmarks for agents.

Key work:
- Scoring engine — **known-vulnerability manifest, not CTF flags**: a scenario
  carries a hidden `vulnerabilities[]` ground truth (CWE + node + points); the
  attacker `report_finding` matches a self-reported finding against it by **CWE
  + node** (neutral ack — no oracle); manifest is operator-only with a reveal
  endpoint + `/arenas/{id}/score`. Per-run metrics (vulns found, steps,
  wall-clock, tokens).
- Benchmark mode: pinned images + seeded secrets; run reports comparing
  model+version+harness across stances.
- Blue-team scoring: sensor alert → `events`; a `detection` objective scores
  when an alert matches a red action within a window.
- **Trace → dataset export**: paired red/blue eval/replay artifacts from
  `events` + JSONL traces.
- **Deep service monitoring + crash oracle (SUT arenas):** a monitor sidecar
  around the service-under-test (logs / crash / sanitizer abort / unhandled-5xx /
  resource exhaustion / optional coverage) → `events` + the defender feed, with a
  crash/abort/5xx counted as a **scored evidence signal**.
- **Evidence-based + CVE-rediscovery scoring (SUT arenas):** *discovery mode* (no
  manifest — monitor signals + self-reported findings, operator triages) and
  *benchmark mode* (pin a version + a CVE manifest → score rediscovery across
  model + version + harness). Per-run metrics (crashes induced, distinct fault
  sites, steps, tokens).

**Acceptance:** an agent run yields a scored report; red-vs-blue produces a
paired dataset; benchmark runs are reproducible from pinned inputs.

### 🟤 Phase 5 — Hardening & multi-provider hosting (AWS) · **M–L**

**Goal:** Nidavellir runs as a hosted platform, not just a LAN tool. (ADR-0006.)

Key work:
- **Ownership/RBAC + quotas** on top of the existing roles: an operator
  sees/destroys their own arenas; per-operator quotas (active arenas, vCPU);
  owner-scoped output exposure (the deferred half of secrets hygiene).
- **Multi-tenant workspaces + SSO** (abstracted from a review of a SicuraNext
  console): **workspaces as the tenancy boundary** (team-shared — a switcher,
  every view scoped — reframing the ownership work above from per-operator →
  per-workspace); **Google OAuth2 SSO** for the human console with server-side
  httpOnly sessions, while the **MCP/agent path stays API-key**; a **dev-login
  bypass that auto-disables** once a real provider is configured; and
  **graduated RBAC with structural guardrails** (auditor / operator / admin /
  owner — can't remove the last owner, only an owner manages owners).
- **Envelope custody for the BYO-AI key**: the control plane stores the
  operator's AI key as **ciphertext it cannot itself decrypt** (per-workspace
  public key at ingest; only the agent process decrypts) — a hardening upgrade
  to BYO-key custody over Fernet-at-rest. No Kong; the gateway owns the seam.
- **`aws` driver**: generic `nodes[]` modules, VPC-per-arena, everything tagged
  `nidavellir:arena_id`, private subnets with **no NAT by default**, SSM access
  (no inbound SSH).
- **Hosting**: EC2 + compose behind TLS (Caddy/ALB) + RDS; secrets via SSM /
  Secrets Manager (instance role, no static keys). ECS/Fargate only when load
  demands.
- **Cost guardrails**: TTL reaper (done) + quotas + AWS Budgets alarm + nightly
  orphan sweep reconciling tagged resources against the DB + per-scenario cost
  estimate at launch.

**Acceptance:** an arena deploys on AWS from the hosted control plane behind TLS
+ auth; teardown leaves zero tagged resources; two operators cannot touch each
other's arenas; budget alarm + orphan sweep verified in a game-day.

### ⚫ Phase 6 — Observability & scale · **M**

Structured JSON logging with `arena_id` correlation; Prometheus metrics (deploy
duration/success, active arenas, queue depth, agent-run counts) + Grafana;
liveness vs readiness probes; worker graceful shutdown + retry policy.

### ⚪ Phase 7 — Operator/auditor console redesign · **L**

Ground-up UI (modern dashboard / dark SOC-console aesthetic; htmx vs SPA decided
in an ADR). **The current console is a temporary surface** — the rework is
**modular and modern**, keeps a **persistent communication link with whatever model
is connected** (extending the connected-model chip into a live model channel), and
**preserves the no-AI human-operator path** (an engagement is fully drivable by a
human with no model). Information architecture: **arena fleet** overview (state-grouped,
filterable), **mission control** per arena (topology, objectives/score),
**agent-trace replay** and **red-vs-blue** views, **auditor** read-only views.
SSE live updates from `events` (replace polling). Browser arena access
(Guacamole/noVNC) — evaluate. No class/leaderboard framing. **Arena wizard UI +
service-monitor panel (SUT arenas):** the guided setup in the console, a live
target health / crash / log panel, and the configurator-consent + HITL-approval
prompts surfaced in the UI.

---

## 4. Target architecture (end of Phase 2)

```
   Operator ─────────────►┌──────────────┐  session   ┌─────────────────────┐
   (author/run/observe)   │   WebUI      │ ─────────► │  FastAPI /api/v1    │
                          │ (Flask+SSE)  │ ◄───────── │  AuthN/Z · scenario │
                          └──────────────┘            │  registry · scoring │
   BYO agent ────────────►┌──────────────┐  api-key   └──────────┬──────────┘
   (Claude Code /         │ MCP Gateway  │ ─────────►            │ enqueue (owner, ttl)
    internal model,       │ stance:      │                       ▼
    any MCP client)       │  attacker /  │            ┌──────────────┐
                          │  MITM /      │            │ Redis broker │
                          │  defender    │            └──────┬───────┘
                          │ scope·budget │                   │◄── beat: reap expired arenas
                          │ audit·trace  │                   ▼
                          └──────┬───────┘        ┌─────────────────────────────────┐
                                 │ run/observe/    │ Celery worker → provider drivers│
                                 │ intercept       │  mock │ docker-local │ os │ aws │
                                 ▼                 └──────┬─────────┬────────┬───────┘
                          (per-stance toolset)            ▼         ▼        ▼
                                                      compose   OpenTofu  OpenTofu
                                 │                    per arena /OpenStack /per-arena VPC
                                 ▼
                          ┌──────────────┐
                          │ PostgreSQL   │ (arenas, scenarios, scores, events,
                          └──────────────┘  agent traces) + JSONL trace store
```

Arena segments have **no egress** by default; sensor/defender nodes report via
a webhook that feeds blue-team scoring and the defender stance.

---

## 5. Definition of Done / quality gates

- [ ] `make check` (ruff + bandit + pytest) green in CI.
- [ ] New behaviour has tests; bug fixes have a regression test.
- [ ] No new bare `except:`; errors logged with context.
- [ ] No secrets in code, logs, or fixtures.
- [ ] Architecturally significant decisions have an ADR.
- [ ] User-facing changes update `docs/OPERATIONS.md` / `docs/API.md`.

ADRs: **0002** auth (roles → operator in Phase 0) · **0003** provider driver &
scenario compilation · **0004** PostgreSQL + Alembic · **0005** MCP agent
gateway protocol, stances & guardrails · **0006** AWS topology & cost controls ·
**0007** software-under-test arenas (service provisioner, gated configurator role
+ consent/HITL, deep monitoring & crash-oracle, discovery-vs-CVE scoring).

---

*Authored 2026-06-10 from a full-repository audit; re-sequenced 2026-06-13 for
the enterprise-arena pivot (dynamic N-node topologies + BYO agents via MCP).
Revisit at the end of each phase and amend via PR.*
