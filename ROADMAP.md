# 🛡️ CyberGuard Roadmap

> A phased plan to take CyberGuard from "working prototype with a Production-Ready
> badge" to a genuinely production-grade, multi-tenant cyber-range platform for
> training **humans and AI agents**.
>
> This roadmap is grounded in a code audit (June 2026) and revised the same month
> to add the product direction: **pluggable deployment providers** (local Docker /
> OpenStack / AWS) and an **agentic-pentest pillar** (labs as scoped, scored
> environments that AI agents can train and be benchmarked on). It stays
> opinionated about sequencing: **correctness and security before features**,
> because the platform turns HTTP input into real cloud infrastructure.

---

## 1. Where the project actually stands

**Strengths (real, keep them):**

- Clean, decoupled architecture: FastAPI ↔ Redis/Celery ↔ OpenTofu ↔ OpenStack.
- Per-lab Terraform workspace isolation (`runs/<id>/` + local-backend override).
- `MOCK_MODE` makes the whole flow demoable and testable with zero cloud cost —
  a genuinely good design choice.
- Dockerised four-service stack with healthchecks.
- Solid docs (`docs/README.md`, `docs/API.md`).

**Reality check on "Production Ready":** the badge reflects *feature* completeness
of the happy path, not operational readiness. The audit found **no authentication,
no tests, no CI, latent Docker-mode path bugs, and several security gaps.** Those
are what this roadmap fixes first.

**Direction (June 2026 revision).** Two structural limits cap the product today:
the orchestrator is hard-wired to a single OpenStack Terraform template with a
frozen 3-VM topology, and the only consumer is a human in a browser. The revised
plan addresses both:

1. **Provider abstraction** — a `RangeProvider` driver interface with `mock`,
   `docker-local` (compose-based container labs: seconds to deploy, zero cloud
   cost, runs on a laptop and in CI), `openstack` (current), and `aws` backends.
   Scenarios describe an abstract topology; each driver compiles it.
2. **Agentic pentest** — an MCP **Agent Gateway** as the only path an AI agent
   has into the range (`deploy_lab`, `get_briefing`, `run_command`,
   `submit_flag`, …), with infrastructure-enforced guardrails (no-egress lab
   networks, step/time budgets, full audit traces) and scenarios doubling as
   reproducible benchmarks scored by the same engine as human leaderboards.
3. **Hosting tiers** — laptop (docker-local) → self-hosted LAN (OpenStack) →
   AWS (per-lab VPC, SSM access, hard cost guardrails).

---

## 2. Audit punch list

Severity: 🔴 High · 🟠 Medium · 🟡 Low. "Fixed ✅" items were addressed in the
Phase-0 pass that introduced this roadmap. Phase references follow the revised
numbering in §3.

| # | Sev | Issue | Where | Status |
|---|-----|-------|-------|--------|
| 1 | 🔴 | **Docker production path bug.** `orchestrator.py` recomputes `TF_SOURCE_DIR`/`RUNS_DIR` from `__file__` (`BASE_DIR.parent.parent`), ignoring `config.py` and the `RUNS_DIR` env var. In the container (`WORKDIR=/app`) this resolves to `/infra/terraform` and `/runs` — neither is where the compose file mounts templates (`/app/terraform`) or state (`/app/runs`). Real-mode deploys in Docker fail / write to non-persisted paths. Mock mode hides it. | `orchestrator.py`, `config.py`, `_load_scenario` | Fixed ✅ (orchestrator consumes `config.py`; Docker `TEMPLATES_DIR` corrected; regression + `tofu init` integration tests, CI installs OpenTofu) |
| 2 | 🔴 | **No authn/authz.** Any caller can deploy/list/destroy any lab. | `api.py` (all routes) | Phase 1 |
| 3 | 🔴 | **Hardcoded Flask secret + `debug=True`** (Werkzeug debugger = RCE). | `webui/app.py` | Fixed ✅ (env-driven) |
| 4 | 🟠 | **No input validation** on `scenario`/`instance_id` before they reach `tofu -var` and workspace paths. | `api.py`, `orchestrator.py` | Phase 1 |
| 5 | 🟠 | **JS syntax error** (`}p`) at end of file broke *all* dashboard JS (polling, topology, destroy). | `webui/static/js/dashboard.js` | Fixed ✅ |
| 6 | 🟠 | **Topology IPs never render.** `dashboard.js` reads `data.attacker_ip.value` etc., but outputs use `attack_vm_floating_ip` (mock) / the `outputs.tf` names. Always shows "Provisioning…". | `dashboard.js:84-116` vs `infra/terraform/outputs.tf` | Phase 1 |
| 7 | 🟠 | **No tests, no CI** at baseline. | repo-wide | Fixed ✅ (suite + CI added) |
| 8 | 🟠 | **Bare `except:`** swallows errors (incl. JSON parse + output read). | `api.py:44-47,99-103`, `orchestrator.py:212` | Phase 1 |
| 9 | 🟠 | **No lab TTL / reaper.** Labs live until manually destroyed → cloud cost + quota leak. | orchestrator/worker | Phase 3 |
| 10| 🟠 | **`random_vulnhub` not wired** to the importer (scenario advertised, `_load_scenario` has no catalog source). | `services/vulnhub-importer/*`, orchestrator | Phase 4 |
| 11| 🟠 | **CSRF** absent on WebUI POST routes. | `webui/app.py` | Phase 1 |
| 12| 🟡 | **CLI is dead code** — `orch.deploy(scenario)` / `destroy()` / `_get_outputs()` are called with the wrong signatures. | `cli.py` | Phase 1 (fix or delete) |
| 13| 🟡 | **`update_deployment` truthiness bug** — `if status:` means an empty-string status is silently ignored; no DB migrations. | `database.py:58-77` | Phase 3 |
| 14| 🟡 | **Secrets in plaintext** in DB `outputs` and logs. | `database.py`, `orchestrator.py` | Phase 3 |

See [`docs/SECURITY.md`](docs/SECURITY.md) for the threat model behind the
security items.

---

## 3. Phased plan

Each phase has a **goal**, **key work**, **acceptance criteria** (how we know it's
done), and a rough **effort** (S ≈ days, M ≈ 1–2 weeks, L ≈ 3–5 weeks for one dev).

> **Revision note (2026-06):** provider abstraction was pulled forward from the
> old Phase 6 ("multi-cloud") to Phase 2 — every later feature gets cheaper to
> build and test once labs can run as containers on a laptop and in CI. Old
> Phase 4 (gamification) is now Phase 5 and absorbs the Agent Gateway, since
> scoring is the shared substrate for human leaderboards and agent benchmarks.

### ✅ Phase 0 — Foundations *(delivered with this roadmap)*

**Goal:** make the project safe to change — you cannot improve what you cannot test.

- [x] Test suite (`tests/`): database, config, and API-contract tests; runs in
      mock mode with no Redis/OpenStack.
- [x] `pytest.ini`, `requirements-dev.txt`, `Makefile` (`make check`).
- [x] CI (`.github/workflows/ci.yml`): ruff lint, bandit scan, pytest+coverage,
      docker image build, compose validation.
- [x] Security quick-wins: env-driven Flask secret + debug; fixed dashboard JS
      syntax error; runtime dirs `.gitignore`d.
- [x] `CONTRIBUTING.md`, `docs/SECURITY.md`, ADRs (`docs/adr/`).

**Acceptance:** `make check` is green; CI runs on every PR.

### 🔴 Phase 1 — Correctness & security hardening · **M**

**Goal:** real-mode Docker deploys work, and the platform is safe on a trusted LAN.

Key work:
1. **Fix path resolution** (#1): make `orchestrator.py` consume `config.py`
   (`BASE_TERRAFORM_TEMPLATE`, `RUNS_DIR`) instead of recomputing from `__file__`;
   fix `config.py` Docker `TEMPLATES_DIR`; add an integration test that runs a
   real `tofu init` against a throwaway local provider in CI.
2. **AuthN/AuthZ** (#2): API-key auth with per-key roles — include an `agent`
   role from day one (Phase 5 needs it); login + session on the WebUI.
   Document in **ADR-0002**.
3. **Input validation** (#4): Pydantic validators — `scenario` must exist in the
   template registry; `instance_id`/friendly-name constrained to `[a-z0-9-]`.
4. **CSRF** (#11) on WebUI POSTs; **rate limiting** (#7 / SECURITY) on the API.
5. **Error handling** (#8): replace bare `except:` with typed handling + logging.
6. **WebUI topology fix** (#6); **CLI** (#12): repair signatures or delete.

**Acceptance:** a real OpenStack deploy succeeds end-to-end from the container
stack; unauthenticated API calls are rejected; `bandit -ll` is clean; integration
test for the provisioning path passes in CI.

### 🔴 Phase 2 — Provider abstraction & local runner · **M** *(new)*

**Goal:** the same scenario deploys on a laptop, on OpenStack, or (later) on AWS;
the orchestrator stops being OpenStack-specific.

Key work:
- Define the **`RangeProvider` driver interface** (`validate / deploy / destroy /
  status`); document in **ADR-0003**.
- Extract the existing logic into drivers behind it: `mock` (from the current
  short-circuit) and `openstack` (current OpenTofu flow, incl. the `runs/<id>/`
  workspace + backend-override pattern) — a pure, regression-tested refactor.
- Add the **`docker-local` driver**: compose project per lab, one isolated
  bridge network per instance, container victim catalog (DVWA, Juice Shop,
  Vulhub CVE images), Kali-rolling attacker container.
- Generalize the OpenStack Terraform template to a generic `nodes[]` module
  (`for_each`) — unfreezes the fixed victim/attacker/monitor topology.
- CI gains a **real end-to-end test** on `docker-local` (deploy → status →
  destroy with actual containers).

**Acceptance:** `basic_pentest`-equivalent container scenario deploys locally in
under a minute with no cloud credentials; the OpenStack path passes the same
regression suite as before the refactor; provider chosen per request/config.

### 🟠 Phase 3 — Multi-tenancy & lab lifecycle · **L**

**Goal:** multiple users/classes share one platform safely and economically.

Key work:
- Users/orgs + RBAC (instructor vs. student vs. **agent**); labs owned by a
  user — you can only see/destroy your own (or your class's).
- **Lab TTL + auto-reaper** (#9): every lab gets an expiry; a periodic Celery beat
  task destroys expired labs. Per-user **quotas** (active labs, vCPU).
- Datastore: SQLite → **PostgreSQL** + SQLAlchemy + **Alembic** migrations
  (ADR-0004); explicit lab state machine; fix `update_deployment` semantics
  (#13); append-only `events` table (lifecycle, submissions, agent commands).
- Secrets handling (#14): stop logging credentials; encrypt or vault sensitive
  outputs.
- Per-tenant network isolation review per provider (security groups / docker
  network separation).

**Acceptance:** two users cannot see/destroy each other's labs; expired labs are
reaped automatically; quota exhaustion returns a clear error.

### 🟠 Phase 4 — Scenario packages · **M**

**Goal:** scenarios become first-class, validated, extensible **packages** —
adding one requires zero code changes.

Key work:
- **v3 package format**: `scenarios/<slug>/` with `scenario.yaml` (abstract
  `nodes[]`/`segments[]` topology, schema-validated), `objectives.yaml` (flags,
  scoring, detection rules), `agent/` (machine-readable scope + engagement
  briefing), optional per-provider overlays, readiness `checks/`.
- Scenario registry endpoint (`GET /api/v1/scenarios`) so the WebUI (and later
  the Agent Gateway) stop hardcoding choices; validation on load; per-provider
  image maps (`kali` → Glance image / AMI / container tag).
- **Wire the VulnHub auto-importer** (#10): catalog source → download/convert/
  upload → emit a generated scenario package; make `random_vulnhub` real.
- Add 2–3 curated scenarios beyond Mr. Robot (incl. container-native ones for
  `docker-local`); difficulty/tag metadata surfaced in the UI.

**Acceptance:** a new scenario can be added by dropping a validated package +
image reference, with no code change; `random_vulnhub` deploys a real imported
image; the same package deploys on at least two providers.

### 🟢 Phase 5 — Scoring & Agent Gateway · **L** *(the product differentiator)*

**Goal:** turn a lab launcher into a *training and evaluation* platform — for
human teams and AI pentest agents, on the same scoring substrate.

Key work:
- **Scoring engine**: objective definitions per scenario (hashed flags,
  command-proof checks); submit-flag → points; leaderboards, per-team progress,
  session timers.
- Blue-team scoring: reward detections in the SOC (Wazuh alert webhook →
  `events`) within a window of the matching red action.
- **Agent Gateway** (new service, MCP server; ADR-0005): `list_scenarios`,
  `deploy_lab`, `get_briefing` (scope + rules of engagement), `run_command`
  (SSH / docker-exec on the attacker node), `submit_flag`, `destroy_lab`.
- **Guardrails, enforced by infrastructure**: lab networks with **no egress**
  (verified by a containment test in CI), per-run step/time budgets, full JSONL
  audit trace of every command, instructor kill switch.
- **Benchmark mode**: pinned images + seeded secrets; metrics = objectives
  solved, steps, wall-clock; run reports. Reference Claude tool-use harness in
  `examples/agent-harness/` (template, not product — any MCP client works).

**Acceptance:** a student can submit a flag and see their score; an instructor
sees a class leaderboard; an AI agent connected via MCP completes a container
scenario end-to-end with every command audited, and a containment test proves
the attacker node cannot reach the internet.

### 🔵 Phase 6 — Observability & scale · **M**

**Goal:** operable in production.

Key work:
- Structured (JSON) logging with correlation IDs per deployment.
- Prometheus metrics (deploy duration, success rate, active labs, queue depth) +
  a Grafana dashboard.
- Distinct liveness vs. readiness probes (current healthcheck hits a real query).
- Horizontal worker scaling guidance; graceful shutdown / task retry policy.

**Acceptance:** dashboards show deploy success rate and active-lab count; a worker
crash mid-deploy leaves the DB in a recoverable state.

### 🟣 Phase 7 — AWS hosted platform · **M–L**

**Goal:** CyberGuard runs as an online platform, not just a LAN tool. (ADR-0006.)

Key work:
- **`aws` driver**: generic `nodes[]` Terraform modules, VPC-per-lab isolation,
  everything tagged `cyberguard:lab_id`; victims/attackers in private subnets
  with **no NAT route by default**; access via SSM Session Manager (no inbound
  SSH exposed).
- **Hosting phase A**: one EC2 running the existing compose stack behind
  TLS (Caddy/ALB) + RDS Postgres; secrets from SSM Parameter Store / Secrets
  Manager (instance role — no static cloud keys). Phase B (ECS Fargate,
  ElastiCache) only when tenancy/load demands it.
- **Cost guardrails (launch blockers)**: TTL reaper + quotas live (Phase 3),
  AWS Budgets alarm, nightly orphan-resource sweep reconciling tagged resources
  against the DB, per-scenario cost estimate shown at launch.

**Acceptance:** a lab deploys on AWS from the hosted control plane behind TLS
and auth; destroying it leaves zero tagged resources; the orphan sweep and
budget alarm are verified in a game-day test.

### ⚪ Phase 8 — UX & product polish · **M**

**Goal:** the experience matches the capability.

Key work:
- Replace 5s polling with SSE live updates from the `events` table.
- Instructor and student views; bulk class provisioning ("spin up 20 labs");
  agent-run review UI (trace replay).
- Browser-based lab access (Guacamole/noVNC) — evaluate.

**Acceptance:** lab status updates without page reload; an instructor provisions a
whole class in one action.

---

## 4. Suggested next two weeks (concrete)

A focused slice of Phase 1 that delivers the most risk reduction:

1. **Day 1–2** — Fix the Docker path bug (#1) + add the `tofu init` integration
   test. This unblocks real deployments; everything else is moot if deploys fail.
2. **Day 3–6** — API-key auth (with roles incl. `agent`) on the API + login on
   the WebUI (#2); write ADR-0002.
3. **Day 7–8** — Pydantic input validation (#4) + `GET /scenarios` registry.
4. **Day 9** — Replace bare excepts (#8); fix WebUI topology key mapping (#6).
5. **Day 10** — Rate limiting + CSRF (#7, #11); turn the CI bandit step blocking.

Exit criterion: a real OpenStack lab deploys from the container stack, behind
auth, with green CI. Then Phase 2 starts with the pure-refactor driver
extraction, which de-risks everything after it.

---

## 5. Target architecture (end of Phase 5)

```
   Browser ──────────────►┌──────────────┐  session   ┌─────────────────────┐
   (human trainees)       │   WebUI      │ ─────────► │  FastAPI /api/v1    │
                          │ (Flask+SSE)  │ ◄───────── │  AuthN/Z · quotas   │
                          └──────────────┘            │  scenario registry  │
   AI agents ────────────►┌──────────────┐  api-key   │  scoring engine     │
   (any MCP client)       │ Agent Gateway│ ─────────► └──────────┬──────────┘
                          │ (MCP server) │                       │ enqueue (owner, ttl)
                          │ scope·budget │                       ▼
                          │ audit traces │            ┌──────────────┐
                          └──────┬───────┘            │ Redis broker │
                                 │ run_command        └──────┬───────┘
                                 │ (ssh/docker-exec)         │◄── beat: reap expired labs
                                 ▼                           ▼
                          ┌─────────────────────────────────────────────┐
                          │ Celery worker → RangeProvider drivers       │
                          │   mock │ docker-local │ openstack │ aws     │
                          └──────┬──────────┬───────────┬─────────┬─────┘
                                 ▼          ▼           ▼         ▼
                            (fixtures)  compose    OpenTofu    OpenTofu
                                        per lab   /OpenStack   /per-lab VPC
                                 │
                                 ▼
                          ┌──────────────┐
                          │ PostgreSQL   │ (users, labs, scenarios, scores,
                          └──────────────┘  events, agent traces)
```

Isolated lab networks have **no egress** by default; the SOC node (Wazuh)
reports back via an alert webhook that feeds blue-team scoring.

---

## 6. Definition of Done / quality gates

Every change merges only when:

- [ ] `make check` (ruff + bandit + pytest) is green in CI.
- [ ] New behaviour has tests; bug fixes have a regression test.
- [ ] No new bare `except:`; errors are logged with context.
- [ ] No secrets in code, logs, or fixtures.
- [ ] Architecturally significant decisions have an ADR.
- [ ] User-facing changes update `docs/README.md` / `docs/API.md`.

Planned ADRs: **0002** auth model · **0003** provider driver interface &
scenario compilation · **0004** PostgreSQL + Alembic · **0005** Agent Gateway
protocol & guardrails · **0006** AWS topology & cost controls.

---

*Roadmap authored 2026-06-10 from a full-repository audit; revised 2026-06-10 to
add provider abstraction, the agentic-pentest pillar, and AWS hosting. Revisit at
the end of each phase and amend via PR.*
