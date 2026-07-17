# 🛡️ Nidavellir Roadmap

> The plan to take Nidavellir from a working container-arena launcher into a
> platform that proves one thing undeniably: **point it at any repo, let a
> bring-your-own agent attack it inside a contained arena, and get a scored,
> replayable, audited result.**
>
> **Two horizons, in sequence** (re-sequenced 2026-07-11):
> 1. **Flagship (now).** A personal open-source flagship — the demo and the
>    benchmark that prove the thesis publicly and build credibility.
> 2. **Internal harness (when ready).** It graduates into an **enterprise's
>    internal harness for testing the agents they build.** The gating question for
>    that graduation — *is the arena tooling rich enough for a real agent to do
>    real work?* — is now a named milestone, not a vague doubt.
>
> The authoritative product statement is [`.agent/proposals/VISION.md`]; this file
> is the sequenced execution plan **from here on**. It stays opinionated —
> **correctness and security before features**, because the platform turns input
> into real infrastructure and hands agents command execution inside it.

**How to read this.** §1 is what's already shipped (the substrate — don't rebuild
it). §2 is the two-horizon bet that re-sequences everything below, with the
**graduation gate** between the horizons. §3 is the forward plan as leverage-ordered
milestones grouped by horizon, each with a goal, the key work, the **worldwide
reference it adopts**, and an acceptance test. §4 is what we **deliberately defer**
and why. §5 is the standing principles every milestone must honour. §6 catalogues
the state-of-the-art we align to, with sources. Legacy phase/backlog IDs (Pn-m) are
cross-referenced so `.agent/backlog/BACKLOG.md` and the ADRs stay traceable.

---

## 1. Where we stand (the shipped substrate — keep, don't redo)

- **Decoupled control plane:** FastAPI ↔ Redis/Celery ↔ provider drivers.
- **Provider abstraction** (ADR-0003): `mock`, **`docker-local`** (real container
  arenas, per-arena bridge networks, seconds to deploy, zero cloud cost — the
  mature, most-exercised path), plus Terraform-skeleton `openstack` / `aws` /
  `libvirt` (VM-class; **not yet a real cloud/VM apply** — see §4 Deferred).
- **API-key auth + roles** admin/operator/agent (ADR-0002); input validation; CSRF
  + API rate limits.
- **PostgreSQL + SQLAlchemy + Alembic** (ADR-0004); explicit lab **state machine**;
  append-only **`events` audit table**; **TTL/stuck reaper**.
- **Secrets hygiene:** log redaction + Fernet-encrypted outputs at rest.
- **Pillar 1 (topology):** scenario schema v3 (`nodes[]` + `segments[]`),
  docker-local compiler, per-provider image map, **Vulhub container importer**.
- **Pillar 2 (MCP gateway):** separate `agent-gateway` service (stdio +
  streamable-HTTP), **server-enforced key↔arena binding**, stances — attacker
  (`run_command`/`report_finding`), defender (`query_events`), MITM (observe-only),
  **configurator** (operator-scripted / HITL / autonomous-double-locked), operator
  authoring; per-session step budget; JSONL trace.
- **Pillar 3 (generation):** BYO-key prompt→v3-spec generator with a **never-auto-
  deploy review gate**; SUT arenas (clone a repo, build to a pinned image via the
  M1 pipeline, white-box read-only source mount); the SUT wizard; the advise-only
  operator **co-pilot** (context-injected, no tools).
- **M1 (repo → running service) — COMPLETE (2026-07-04):** repo-introspection +
  deterministic build tier (honor a shipped Dockerfile) + **verified LLM Dockerfile
  synthesis** (Repo2Run loop) + `service.package` install, all version-pinned +
  arena-labeled + reclaimed. *(Remaining tier work: compose / devcontainer /
  buildpack **execution** paths are classified but not yet executed — need a
  compose runtime, the `devcontainer` CLI, or the `pack` binary.)*
- **M2 (monitoring + validators + scoring) — COMPLETE (2026-07-13):** crash oracle
  (`monitor.py`), deterministic "perfect-verification" validators (`validators.py`),
  and the structured scored verdict with benchmark/discovery modes + milestone
  partial credit (`scoring.py`), all event-backed and provider-agnostic. ADR-0009
  Accepted. *(Remaining: the headless-browser execution oracle that upgrades the XSS
  validator from reflection to confirmed-execution rides with M4.)*
- **Ops:** `MOCK_MODE` makes the whole flow demoable/testable with no cloud;
  `make check` (ruff + bandit + pytest) green; CI on SQLite + Postgres.

> The June-2026 correctness/security audit and the SUT-wizard hardening pass are
> **complete** (Docker-path, authn/authz, CSRF, TTL reaper, secrets-at-rest, SSRF
> guard `netguard`, key↔arena binding D1, `/events` ground-truth leak, deploy
> observability, image-existence checks, event-loop-blocking fix). Full record:
> git history + `.agent/STATE.md`.

---

## 2. The two-horizon bet (what this re-sequencing is for)

Nidavellir was ~60% built across seven parallel fronts and 100% on none. The 2026-07-01
correction was right — **depth over breadth** — and the 2026-07-11 clarification sharpens
it further: we now know **who this is for and in what order.**

> **Horizon 1 — Flagship (now).** A personal open-source flagship. Success =
> *the thesis is undeniable in one demo and one public benchmark.* Audience: the
> security/AI community, and a future evaluation of whether it's ready for
> enterprise use.
>
> **Horizon 2 — Internal harness (when ready).** It graduates into an **enterprise's
> internal harness for testing the agents they build.** Success = *point your own
> agent at a target, let it do real offensive work, and get a scored,
> regression-comparable, deeply-observable result across agent versions.*

**The differentiator, restated.** No one combines a BYO-agent MCP harness **+**
auto-provision-any-OSS **+** crash-oracle scoring. XBOW/Strix are agents (no arena);
Cybench/CVE-Bench are fixed target sets (no arbitrary-repo provisioning); GOAD/Ludus
are ranges (no agent seam or scoring). Nidavellir's data-defined engine + gateway +
events spine is the substrate that makes the combination cheap. **The moat is the
scoring/crash-oracle layer (M2) — now built** (crash oracle + deterministic
validators + structured scoring, ADR-0009). Most effort before it went into the
commodity layer (topology, providers, console); with the vault in place, the next
work is M3 — turning each scored run into a comparable, replayable eval and shipping
the flagship proof.

**The spine serves both horizons.** M1 → M2 → M3 (reliable provisioning → deep
monitoring/scoring → benchmark/eval + the flagship proof) *is* Horizon 1, and it is
also the foundation every internal use depends on. So it comes first, unchanged in
priority.

### The graduation gate (Horizon 1 → Horizon 2)

Before Nidavellir is worth introducing in an enterprise as an agent-test harness, all
of these must be true. This is the honest answer to *"I'm not sure the tooling is
enough":*

1. **The spine is real** — M1+M2+M3 land end-to-end: a BYO agent stands up an
   arbitrary repo, attacks it, and a crash/validated-finding produces a structured,
   replayable score (not a demo-only happy path).
2. **A real agent can do real work** — the arena exposes the tools a serious
   offensive agent actually centres on (not just `run_command`): headless browser,
   code-exec sandbox, HTTP intercept proxy, file transfer, SSH tunnelling (M4).
   *This is the specific gap behind the "is the tooling enough?" doubt.*
3. **Iteration is measurable** — the same agent at version N vs N+1 on the same
   arena set yields comparable rows, and traces export into an eval stack we
   actually use (Langfuse/Phoenix) (M5).

Until the gate is met, Nidavellir stays a flagship. After it's met, it's a tool an
enterprise runs.

---

## 3. The forward plan (leverage-ordered, grouped by horizon)

| # | Milestone | Horizon | Legacy | Effort | Why it's here |
|---|-----------|---------|--------|--------|---------------|
| **M1** | Reliable *repo → running service* provisioning | H1 (spine) | P1-6, Field-C | L | ✅ **DONE** — the core unlock |
| **M2** | Deep monitoring + crash oracle + structured scoring | H1 (spine) | P4-1/6/7 | L | ✅ **DONE** — the moat; makes any target scorable |
| **M3** | Benchmark, eval layer & the **flagship proof** | H1 (spine) | P4-2/3/4, P5-4 | M | 🔴 **THE next thing** — turns runs into comparable, replayable datasets **+ ships the demo/benchmark that makes it a flagship** |
| **M4** | Agent-grade arena tooling & fail-closed guardrails | H2 | P2-2/3/4 | M | **Answers "is the tooling enough?"** — the tools a real agent needs to do real work |
| **M5** | Regression & eval pipeline for iterating on an agent | H2 | P4-3/4, P5-4 | M | The internal-harness heart: compare agent vN vs vN+1, export to our eval stack |
| **M6** | *(opportunistic)* LLM-application-as-target arenas | H2 | P3-5, AI-INT §4 | M | Directly relevant to testing the **agentic products** an enterprise builds |

Everything the previous roadmap listed as M4 (OAuth/tool-supply-chain), M5 (in-browser
VNC console), M7 (purple-team), and M8 (multi-tenant hosting) is **deferred — see §4.**

---

### ✅ M2 — Deep monitoring + crash oracle + structured scoring · **H1 · L · DONE (2026-07-13)**

**Goal.** A target with **no pre-known vulnerability manifest is still scorable** —
"the agent made it fall over" is first-class evidence. This is the capability that
separates a demo from something that covers real-world issues, it's the platform's
moat, and it is the payoff of the flagship demo.

**Shipped.** All three parts of ADR-0009 landed: the monitor / crash oracle
(`monitor.py` + the `monitor_arenas` beat task), the deterministic validators
(`validators.py` — active reflected-XSS/marker/OAST probes + passive crash
correlation, SSRF-safe arena-bound `http_fn`, tri-state `confirmed`), and the
structured scored verdict (`scoring.py` — Inspect-style `Score`, benchmark +
discovery modes, milestone Progress Rate that scores even a failed run), wired into
`POST /arenas/{id}/findings` and `GET /arenas/{id}/score`. Verification verdicts are
operator-only (redacted from the agent feed). `make check` green (636 tests). See
ADR-0009 for the full design. *The spec below is retained as the design record.*

**Monitor sidecar** around the service-under-test → `events` + the defender feed:
logs, crashes/panics, **sanitizer aborts** (ASan/UBSan when built with them),
unhandled 5xx, resource exhaustion, optional coverage. Model on **OSS-Fuzz /
ClusterFuzz** — a crash or sanitizer abort is a scored signal.

**Deterministic validators, not vibes.** Adopt the **XBOW / Project-Naptime "perfect
verification"** principle: a finding is accepted only when programmatically
confirmed — headless-browser confirmation that an XSS payload executed, an OAST/SSRF
out-of-band callback, an ASan trigger for a memory bug, a DB-state check. Model the
target-condition graders on **CVE-Bench**'s 8 standardized attack-outcome monitors.
*(The headless-browser XSS validator is shared with M4's headless-browser tool —
build once.)*

**Structured, machine-parseable verdicts.** Emit an **Inspect-style `Score`** (value
∈ binary | numeric | categorical, plus `answer`, `explanation`, `evidence`,
`metadata`) — never free text. Deterministic checks first, LLM-as-judge (majority
vote) only where unavoidable, always JSON.

**Partial credit, not win/lose.** Grade **subtask/milestone progress** (Cybench
ordered subtasks; AutoPenBench Command/Stage Milestones → a **Progress Rate even on
failed runs**), so weak and strong agents are distinguishable and hard targets stay
informative. *(This is what will let an enterprise tell a weak agent build from a strong
one in Horizon 2 — build it now.)*

**Two scoring modes:** *discovery* (no manifest — monitor signals + operator-triaged
self-reported findings) and *benchmark* (pin a version with a CVE manifest → score
CVE-rediscovery). Per-run metrics: vulns found, crashes/distinct fault sites induced,
milestones reached, steps, wall-clock, tokens, cost.

**Acceptance.** An agent run yields a structured JSON scored report; a crash induced
on a no-manifest target scores; an XSS is only credited after headless-browser
confirmation; a failed run still reports a Progress Rate. → **ADR-0009 (scoring,
validators & eval).**

---

### 🟠 M3 — Benchmark, eval layer & the flagship proof · **H1 · M · IN PROGRESS**

**Goal.** Every arena run is a comparable, replayable, exportable eval — and this is
the milestone that makes Nidavellir a **flagship** rather than a codebase: it ships
the demo and the public benchmark.

**Progress (2026-07-14, ADR-0010).** Most of the eval layer landed:
- **Eval-export** — a run projects to the convergent dataset row (`input /
  expected_output / metadata / tags / source_trace_id` + embedded M2 Score) with the
  full model+scaffold+cost tuple (`eval_export.py`, `GET /arenas/{id}/eval-export`,
  operator-only). Gateway trace OpenInference/OTel-GenAI aligned for zero-reshape
  import into Langfuse/Phoenix.
- **Reference harness** (`cyber-range/services/reference-harness/`) — an injectable
  BYO agentic loop that plays an arena over MCP (ScriptedBrain + AnthropicBrain),
  budget-bounded; a **concurrency-capped batch suite** that emits a dataset JSONL +
  summary; a production REST control plane; and **deterministic replay**.
  Live-verified: a scripted agent drove the real gateway against a real docker arena
  and produced a scored eval row, keyless.
- **Flagship run in hand (2026-07-17).** A bring-your-own **Claude Code** agent, over
  the MCP gateway against a live `container_web_pentest` (DVWA) arena, found and
  **confirmed 11 real vulnerabilities** (XSS, SQLi, OS command injection, LFI,
  unrestricted-upload→RCE, CSRF, …) into one scored, matched verdict (6/6 manifest,
  score 1.0). The thesis is demonstrated end-to-end on a real target.
- **Operator verification path (ADR-0009 item 6).** `POST …/findings/{id}/verify`
  (confirm/refute) and `POST …/findings/manual` let a human confirm the findings a
  deterministic validator can't auto-prove (auth-gated web vulns). An operator
  `confirmed` flips the `verified_exploit` milestone and adds `confirmed_points`, so
  a genuinely-proven run is no longer capped at 0.8. The console splits benchmark
  (scored manifest) from discovery/SUT (no gamified scoring).

**Remaining:** difficulty tiers / First-Solve-Time, guided-vs-unguided modes, a
held-out set, the SSE live feed / monitor panel, broadening the auto-validators
(command-injection / LFI / upload-RCE so more findings self-confirm), and the
polished, **recorded flagship demo** cut — the last M3 acceptance deliverable.

**The flagship proof (the deliverable that earns attention).** One unforgettable
end-to-end, on one screen, in two minutes: *point at a well-known OSS repo → a BYO
Claude agent finds and **proves** a real bug (headless-confirmed XSS or an ASan crash)
→ a scored JSON report + full trace.* Record it, write it up, publish it. Nobody
remembers "MCP gateway with per-key budgets"; everybody remembers "I pointed it at a
repo and it caught a real bug and scored it."

**Report the whole tuple, not just a score.** The strongest convergent lesson across
METR, UK-AISI, HAL and SWE-bench's standardized-scaffold track: a published number
conflates model capability with what the **scaffold** allowed. Since agents are
bring-your-own over MCP, **scaffold is a first-class row field** — record
`model + version + harness/scaffold + stance + task-set + score + steps + cost +
pass@k`. Ship an optional **reference harness** (thin Claude/Anthropic-SDK MCP loop)
for apples-to-apples runs. *(This reference harness is dual-purpose: it powers the
flagship demo now, and in Horizon 2 it's the neutral baseline the enterprise's own agent
is measured against — build it well.)*

**Difficulty & anti-saturation.** Attach a difficulty tier and a **First-Solve-Time**
estimate (Cybench's human-anchored axis) to each arena; report the hardest tier an
agent cleared. Offer **guided vs unguided** modes so hard arenas stay informative at
0% unguided solve rate. Keep a **held-out / non-public** set to resist contamination.

**Trace → dataset (traces you already write become evals).** Align the JSONL trace
schema to **OpenTelemetry GenAI** semantic conventions + **OpenInference** span kinds
(`execute_tool`, `invoke_agent`, `gen_ai.*`, `gen_ai.conversation.id`) so traces flow
into Langfuse/Phoenix/Braintrust unmodified. Adopt the convergent dataset record
shape — `input` / `expected_output` / `metadata` / `tags` + a `source_trace_id`
back-link.

**Deterministic replay.** Checkpoint arena + run state so a run can be **replayed or
forked** (Inspect's compact `.eval` transcript is the model).

**Demo-grade polish (small, in service of the flagship).** SSE live feed (retire 5s
polling, P7-3) and a live service-monitor panel surfacing M2's crash/log/health
signals — enough that the demo *looks* like a product. **Not** the full in-browser
VNC/terminal build (deferred, §4).

**Technique tagging.** Tag every agent action and finding with **MITRE ATT&CK** and,
for AI targets, **MITRE ATLAS** + **OWASP LLM Top 10** IDs — the shared substrate
that makes coverage legible.

**Acceptance.** The flagship demo runs end-to-end and is published; two BYO agents on
one benchmark arena produce comparable rows (incl. scaffold + cost + pass@k); a
completed run replays deterministically from its trace; a run exports as a ready-to-use
eval dataset. → **ADR-0009.**

---

### 🟢 M4 — Agent-grade arena tooling & fail-closed guardrails · **H2 · M**

**Goal.** Make the arena rich enough that a **real, serious offensive agent** (the
kind an enterprise builds) can do real work — not just shell one-liners. **This is the
direct, concrete answer to "I'm not sure the tooling this project uses is enough."**
Today the attacker stance is essentially `run_command` + `report_finding`; a
sophisticated agent is starved on that alone.

**Complete the attacker toolset to match the field.** Ship, as first-class MCP tool
schemas layered over the shell — the primitives every serious offensive agent (XBOW,
Strix, CAI) centres on:
- **`upload_file` / `download_file`** (get payloads in, evidence out).
- **HTTP interception proxy** (inspect/replay/modify requests — the core web-testing
  primitive).
- **Headless browser** (JS-heavy targets; **doubles as the M2 XSS validator** — one
  build serves both).
- **Python / code-exec sandbox** for PoC development (a confined, resource-capped
  scratch container — *not* on the orchestrator's docker.sock; see the isolation note).
- **SSH tunnelling** (pivot/port-forward through the foothold).

**Durable, fail-closed guardrails.** Cross-process **budgets** (step/time/token/cost,
auto-reset windows, **fail-closed**), RPM/TPM + max-parallel + runaway-loop
(`max_iterations`) guards, per-command timeout, and a **two-scope kill-switch** that
drains in-flight commands, hard-stops, and flushes traces. *(A runaway agent burning
tokens/cost is a real problem even for solo/internal use — this earns its place in
Horizon 2 while OAuth/multi-tenant auth does not.)* Model on LiteLLM-proxy enforcement.

**Minimal isolation for the code-exec sandbox.** The moment a capable agent gets a
code-exec tool, confinement matters even on a single host: the sandbox is a
CPU/mem-capped, egress-locked, filesystem-off-by-default container, and code-exec runs
through the **worker**, never the orchestrator's root-equivalent docker.sock. *(Full
docker.sock re-architecture / rootless daemon is deferred, §4 — but the sandbox must
not widen the blast radius.)*

**Explicitly out of M4** (deferred, §4): MCP OAuth 2.1, tool-supply-chain defenses
(tool-poisoning/rug-pull hardening), and multi-agent concurrency. We trust our own
agent and run single-tenant; these are product/multi-tenant concerns.

**Acceptance.** A BYO agent uses the headless browser to confirm a reflected XSS, runs
a Python PoC in the sandbox, uploads a payload and downloads captured evidence, and
tunnels to an internal-segment service through the foothold — all through MCP tool
schemas, all traced; a budget breach fails closed and freezes the arena; a CI
containment test proves the code-exec sandbox can't reach the internet or cloud
metadata. → **ADR-0005** (gateway protocol/stances/guardrails) extended.

---

### 🔵 M5 — Regression & eval pipeline for iterating on an agent · **H2 · M**

**Goal.** The internal-harness heart: make Nidavellir the thing an enterprise runs *every
time it changes its agent.* One run is a demo; a **repeatable regression pipeline
across agent versions** is a tool.

- **Agent-version comparability.** Run agent `vN` and `vN+1` over the same arena set;
  produce a diffable report (score deltas, new regressions, newly-solved arenas,
  cost/step deltas per arena). Built on M3's row schema + held-out sets.
- **Export into our eval stack.** One-click / API promotion of any run or span into
  **Langfuse / Phoenix / Braintrust** as a dataset item, using M3's OpenInference-aligned
  traces — so the agent team debugs and evals in tools they already live in.
- **Deterministic replay at scale.** Batch-replay a suite from pinned specs; a run that
  can't be reproduced byte-for-byte is a bug, not a result.
- **Reference-harness baseline.** M3's thin harness becomes the fixed control: "our
  agent vs the reference loop on the same task set" is the headline internal metric.

**Acceptance.** A single command runs two agent builds over a pinned arena suite and
emits a comparison report + an exported Langfuse/Phoenix dataset; re-running the suite
reproduces identical arena state; a regression (vN+1 scores lower on arena X) is
surfaced automatically. → **ADR-0009** extended.

---

### 🟣 M6 — LLM-application-as-target arenas · **H2 · M · opportunistic**

**Goal.** A new arena archetype where the **victim is an LLM application** — kept in
scope because it's directly relevant to an enterprise testing the **agentic products** it
builds, and it's naturally container-shaped (cheap on docker-local). Packs map to
**OWASP Top 10 for LLM Apps (2025)** and the **OWASP Top 10 for Agentic Applications
(ASI01–ASI10)**.

Ship, in order of signal-per-effort, only after the spine + M4/M5 are solid:
- **Prompt-injection RAG** (LLM01) — exfiltrate a planted secret via indirect injection.
- **System-prompt leakage** (LLM07) / **sensitive-info disclosure** (LLM02).
- **Improper output handling** (LLM05) — model output → XSS/SSRF/RCE downstream
  (**where M1's SUT provisioning + M2's validators shine**).
- **Excessive agency / tool abuse** (LLM06 / ASI02).

Verdicts are machine-checkable from the app's own logs (reuse M2). Integrate **garak**,
**PyRIT**, and **promptfoo** strategies as reference attacker tooling — never as "our
AI." The **MITM stance becomes uniquely valuable here** (memory/context poisoning ASI06,
inter-agent poisoning ASI07).

**Acceptance.** One prompt-injection RAG lab scored end-to-end (secret-exfil detected
from app logs). *(Purple-team defender scoring around this archetype is deferred, §4.)*

---

## 4. Deliberately deferred (out of scope for both horizons — for now)

Cutting these is a decision, not an omission. **None are needed for a personal
open-source flagship or a single-team internal harness.** Each is a
product/multi-tenant/hosted-SaaS concern; revisit only if Nidavellir becomes a
commercial product or a multi-team platform.

- **MCP OAuth 2.1 & tool supply-chain defenses** (was M4). API-key auth is fine
  single-tenant with a trusted agent. Tool-poisoning/rug-pull/confused-deputy hardening
  matters when you connect *untrusted* third-party tools — not your own agent.
- **In-browser VNC / Guacamole desktop + full web-terminal** (was M5). The "no-AI human
  path" stays honored at the SSH/console level (containment principle below), but the
  heavy browser-access build is a hosted-product feature. M3 ships only demo-grade SSE +
  a monitor panel.
- **Purple-team paired telemetry & detection scoring + CALDERA baselines** (was M7).
  Real red-vs-blue value, but it needs a second (defender) agent and multi-agent
  concurrency; out of scope until there's a concrete internal need to test defender
  agents.
- **Multi-provider hosting: real cloud/VM apply (AWS, libvirt boot), multi-tenant
  RBAC/SSO/workspaces, docker.sock re-architecture** (was M8). docker-local is the whole
  substrate a flagship and an internal harness need. (The *minimal* code-exec-sandbox
  isolation in M4 is the exception — that's a blast-radius fix, not hosting.)
- **Multi-agent concurrency / red-vs-blue** (was M4/M7). Single-agent, single-tenant is
  the whole Horizon-2 requirement; concurrency rides with purple-team if it ever lands.

> **If the horizon changes** (Nidavellir becomes a product, or multiple enterprise
> teams use it), re-promote these in roughly this order: OAuth + isolation hardening →
> multi-tenant RBAC/SSO → real cloud apply → purple-team. The old §5 of the prior
> roadmap has the detailed designs; they're preserved in git history.

---

## 5. Standing principles (every milestone honours these)

- **Scope boundary (load-bearing).** Nidavellir builds the **integration surface and
  the safe substrate only** — the MCP connectors, validated schemas, provider
  compiler, sandbox, monitor, consent gate, scoring engine, trace store. **The AI is
  always bring-your-own**, under the user's own key and model. We ship no AI attacker,
  defender, judge, or generator; reference harnesses/connectors are thin, optional
  wiring samples. *(This is also the positioning asset: only a non-agent platform can
  credibly be the neutral place to test any agent — including the enterprise's own.)*
  (`cyberguard-ai-scope-boundary`)
- **AI-centered, never AI-required.** Built for testing AI agents and MCP-compliant
  throughout, but **no arena may depend on a model** — every arena stays drivable by a
  human (SSH/console + manual finding submission). (`cyberguard-ai-optional`)
- **Containment is the primary control.** Arena segments have **no egress** by default
  (provider-enforced), + optionally an allowlisted apt/pip mirror; a CI containment test
  proves an arena node — **and the M4 code-exec sandbox** — can't reach an external
  canary or cloud metadata. Never-auto-deploy generated infra; consent-gated,
  HITL-approved, time-boxed configurator with a hard privilege boundary.
- **Correctness & security before features.** Every milestone: `make check` green; new
  behaviour has tests + a regression test for bug fixes; no new bare `except:`; no
  secrets in code/logs/fixtures; architecturally significant decisions get an ADR;
  user-facing changes update `docs/`.
- **Verify the product, not the tests.** "Green pytest against an explicit provider" is
  not "works through the stack" — live-verify through the actual compose product.
  (`cyberguard-verify-the-product-not-tests`)

---

## 6. State of the art we align to (references)

Design patterns and tools this roadmap deliberately adopts. (Vendor performance figures
are self-reported; treat as directional.)

**Repo → runnable image (M1, done)**
- Cloud Native Buildpacks / Paketo · https://buildpacks.io · https://paketo.io
- Railpack (Nixpacks successor) · https://github.com/railwayapp/railpack
- Dev Containers spec · https://containers.dev
- Repo2Run — LLM Dockerfile synthesis w/ verified-build + rollback (~86%) · https://arxiv.org/abs/2502.13681
- BuildKit git-context builds · https://docs.docker.com/build/concepts/context/

**Monitoring, validators & scoring (M2–M3, the moat + flagship)**
- OSS-Fuzz / ClusterFuzz + sanitizers — crash/abort as evidence · https://google.github.io/oss-fuzz/
- XBOW deterministic validators; Project Naptime "perfect verification" · https://xbow.com/blog/core-components-ai-pentesting-framework · https://projectzero.google/2024/06/project-naptime.html
- Cybench (subtasks, guided/unguided, First-Solve-Time) · https://cybench.github.io · https://arxiv.org/abs/2408.08926
- CVE-Bench (8 standardized attack-outcome graders) · https://arxiv.org/abs/2503.17332
- AutoPenBench (Command/Stage milestones → Progress Rate) · https://arxiv.org/abs/2410.03225
- UK-AISI Inspect (`Score`, Solver/Scorer, `.eval` transcripts) · https://inspect.aisi.org.uk
- METR Task Standard (`score()→float|None`) · https://github.com/METR/task-standard
- Meta CyberSecEval v3/v4 (ATT&CK mapping, FRR, AutoPatch) · https://github.com/meta-llama/PurpleLlama
- Reporting model+scaffold+cost+pass@k — HAL / AISI elicitation-disclosure / SWE-bench standardized-scaffold · https://arxiv.org/abs/2510.11977

**Agent tooling, trace & eval pipeline (M4–M5, the internal harness)**
- Offensive-agent toolsets — XBOW · Strix (Graph of Agents) https://github.com/usestrix/strix · CAI https://github.com/aliasrobotics/cai · PentestGPT https://github.com/GreyDGL/PentestGPT
- OpenTelemetry GenAI semconv + OpenInference span kinds · https://opentelemetry.io/docs/specs/semconv/gen-ai/ · https://github.com/Arize-ai/openinference
- Trace→dataset / regression: Langfuse · https://langfuse.com/docs/evaluation/experiments/datasets · Arize Phoenix · https://github.com/Arize-ai/phoenix · Braintrust
- Budget/rate fail-closed enforcement — LiteLLM Proxy · https://docs.litellm.ai/docs/proxy/users

**LLM-app targets (M6, opportunistic)**
- OWASP Top 10 for LLM Apps 2025 · https://genai.owasp.org/llm-top-10/
- OWASP Top 10 for Agentic Applications (ASI01–10) · https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/
- garak · https://github.com/NVIDIA/garak · PyRIT · https://github.com/microsoft/PyRIT · promptfoo · https://www.promptfoo.dev/docs/red-team/
- AgentDojo (indirect-injection agent-security benchmark) · https://arxiv.org/abs/2406.13352
- MITRE ATLAS (AI ATT&CK) · https://atlas.mitre.org/

**Ranges & references (substrate)**
- GOAD (data-defined AD labs, variants) · https://github.com/Orange-Cyberdefense/GOAD
- Vulhub (compose CVE envs) · https://github.com/vulhub/vulhub · DVWA · Juice Shop
- MCP spec · https://modelcontextprotocol.io

**Deferred-topic references** (for when/if the horizon changes — §4): MCP OAuth 2.1 &
tool-poisoning (Invariant Labs, Docker/IBM/Lasso gateways); Ludus ranges-as-code;
Apache Guacamole / noVNC / ttyd; MITRE CALDERA + GameBoard + Atomic Red Team + VECTR.
Designs preserved in git history of the prior roadmap.

---

## 7. Architecture decision records

- **0002** auth model (roles admin/operator/agent) — Accepted
- **0003** provider driver interface & scenario compilation — Accepted
- **0004** datastore: PostgreSQL + Alembic — Accepted
- **0005** MCP agent gateway protocol, stances & guardrails — to extend (M4: complete toolset + fail-closed guardrails)
- **0007** software-under-test arenas — Accepted (provision→configure→monitor→score spine complete)
- **0008** repo→image build pipeline — Accepted (M1 complete; buildpack/compose/devcontainer execution tiers pending)
- **0009** scoring, deterministic validators, monitor — Accepted (M2 complete; M3/M5 extend the trace→eval + regression format)

*Deferred ADRs (revisit only if the horizon changes, §4): 0006 AWS topology & cost
controls; 0010 MCP OAuth 2.1 & tool supply-chain defenses.*

---

*Re-sequenced 2026-07-11 around two horizons — a personal open-source **flagship**
(M1–M3 spine: prove the thesis with a demo + benchmark) graduating into an enterprise's
**internal harness for testing its own agents** (M4 agent-grade tooling, M5 regression
pipeline, M6 LLM-app targets), gated by an explicit graduation check. Product/
multi-tenant concerns (OAuth, hosting, purple-team, VNC console) are deliberately
deferred (§4). Revisit at the end of each milestone and amend via PR. North star:
`.agent/proposals/VISION.md`.*
