# 🛡️ Nidavellir Roadmap

> The plan to take Nidavellir from a working container-arena launcher into an
> **agentic arena forge for testing skills in dynamic environments — and, above
> all, for testing AI agents.** It provisions arbitrary multi-machine vulnerable
> topologies and exposes them, through **MCP gateways**, to bring-your-own agents
> placed as **attacker / MITM / defender**, then scores and traces every run.
>
> The authoritative product statement is [`.agent/proposals/VISION.md`]; this file
> is the sequenced execution plan **from here on**. It stays opinionated —
> **correctness and security before features**, because the platform turns input
> into real infrastructure and hands agents command execution inside it.

**How to read this.** §1 is what's already shipped (the substrate — don't rebuild
it). §2 is the strategic bet that re-sequences everything below. §3 is the forward
plan as eight leverage-ordered milestones (M1–M8), each with a goal, the key work,
the **worldwide reference it adopts**, and an acceptance test. §4 is the standing
principles every milestone must honour. §5 catalogues the state-of-the-art we align
to, with sources. Legacy phase/backlog IDs (Pn-m) are cross-referenced so
`.agent/backlog/BACKLOG.md` and the ADRs stay traceable.

---

## 1. Where we stand (the shipped substrate — keep, don't redo)

- **Decoupled control plane:** FastAPI ↔ Redis/Celery ↔ provider drivers.
- **Provider abstraction** (ADR-0003): `mock`, **`docker-local`** (real container
  arenas, per-arena bridge networks, seconds to deploy, zero cloud cost — the
  mature, most-exercised path), plus Terraform-skeleton `openstack` / `aws` /
  `libvirt` (VM-class; **not yet a real cloud/VM apply** — see M8).
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
  deploy review gate**; SUT arenas (clone a repo into a fresh Ubuntu box at
  `/opt/sut`; white-box read-only source mount; build-from-source behind a flag);
  the SUT wizard; the advise-only operator **co-pilot** (context-injected, no tools).
- **Ops:** `MOCK_MODE` makes the whole flow demoable/testable with no cloud;
  `make check` (ruff + bandit + pytest) green; CI on SQLite + Postgres.

> The June-2026 correctness/security audit and the SUT-wizard hardening pass are
> **complete** (Docker-path, authn/authz, CSRF, TTL reaper, secrets-at-rest, SSRF
> guard `netguard`, key↔arena binding D1, `/events` ground-truth leak, deploy
> observability, image-existence checks). Two structural authz items remain, folded
> into **M8** (per-operator identity D2; least-privilege bootstrap key D3). Full
> record: git history + `.agent/STATE.md`.

---

## 2. The strategic bet (what this re-sequencing is for)

Today Nidavellir is ~60% built across seven parallel fronts and 100% on none. The
correction is **depth over breadth: pick one defensible vertical and make it fully
real.** That vertical is the one nobody else has end-to-end:

> **Point Nidavellir at *any* GitHub repo → it stands the service up reliably →
> monitors it deeply → and scores a bring-your-own agent that pentests it, white-
> or black-box, over MCP.**

No one combines a BYO-agent MCP harness **+** auto-provision-any-OSS **+** crash-
oracle scoring. XBOW/Strix are agents (no arena); Cybench/CVE-Bench are fixed target
sets (no arbitrary-repo provisioning); GOAD/Ludus are ranges (no agent seam or
scoring). Nidavellir's data-defined engine + gateway + events spine is exactly the
substrate that makes the combination cheap.

**So M1–M3 (reliable provisioning → deep monitoring/scoring → benchmark/eval) are
the spine and come first.** M4 hardens the seam agents connect through; M5 makes it
usable and human-drivable; M6–M7 expand to the two archetypes with the strongest
market pull (LLM-app targets, purple-team); M8 is hosting. **Deferred until the
spine is compelling:** real cloud/VM apply, multi-tenancy/SSO — real work, no payoff
until the core lands.

---

## 3. The forward plan (leverage-ordered)

| # | Milestone | Legacy | Effort | Why it's here |
|---|-----------|--------|--------|---------------|
| **M1** | Reliable *repo → running service* provisioning | P1-6, Field-C, "#17" | L | The core unlock; today's SUT setup is model-guess + operator-fix and unreliable |
| **M2** | Deep monitoring + crash oracle + structured scoring | P4-1/6/7 | L | What makes it cover *real-world* issues without a pre-known CVE list |
| **M3** | Benchmark & eval layer (arenas as reproducible benchmarks) | P4-2/3/4, P5-4 | M | Turns runs into comparable, replayable, exportable datasets |
| **M4** | MCP gateway hardening + multi-agent | P2-2/3/4/6/11 | M–L | Production-grade seam; unlocks concurrent red-vs-blue |
| **M5** | Console, browser access & the no-AI human path | P7-3/5/6/8, P1-3/7 | M–L | UI/UX bar; make it usable and drivable with no model |
| **M6** | LLM-application-as-target arenas | P3-5, AI-INT §4 | M | New archetype with the strongest AppSec/AI-security pull |
| **M7** | Purple-team paired telemetry & detection scoring | P4-6, P4-9, AI-INT §5 | M | The red-vs-blue flywheel + defender scoring |
| **M8** | Hardening & multi-provider hosting | P5-* , P6-* | L | Hosted, multi-tenant, real cloud/VM — last |

---

### 🔴 M1 — Reliable "repo → running service" provisioning · **L**

**Goal.** Point at any public repo and get a **healthy running service on a pinned,
reproducible image**, with zero manual steps for the common case and a verified,
reviewable fallback for the rest. This replaces today's fragile "model drafts shell
commands into a bare Ubuntu box, operator corrects them" flow (which the field log
showed getting `npm`/`python3`/port wrong on real repos).

**The build pipeline — deterministic-first, LLM-fallback (three tiers):**
1. **Honor what the repo already ships.** If it has a `Dockerfile`, `compose.yaml`,
   or `devcontainer.json`, use it directly (BuildKit; `devcontainer up`). Most real
   projects do — this is the cheapest, most reliable path.
2. **Zero-config detection** for the rest. Adopt **Cloud Native Buildpacks**
   (`pack` + Paketo — the industry standard behind Heroku Fir / Google Cloud, with
   formal `detect → build → export` semantics for Node/Python/Go/Java/Ruby/PHP) as
   the default no-Dockerfile engine, or **Railpack** (Nixpacks' maintained successor)
   as a lighter alternative. Detection keys off indicator files (`package.json`,
   `requirements.txt`/`pyproject.toml`, `go.mod`, `pom.xml`, `Gemfile`, …).
3. **LLM Dockerfile synthesis with a verified-build loop** when detection fails.
   Follow the **Repo2Run** pattern (ByteDance, arXiv:2502.13681 — ~86% buildable on
   arbitrary Python repos): the BYO model proposes build steps, we **actually build
   and run each in an isolated container, roll back failed steps, and keep only what
   builds green**. Never ship a one-shot unverified LLM Dockerfile (pure-LLM
   hallucinates packages ~20% of the time).

**Grounding (the thing that makes all three tiers work).** A **repo-introspection
step** runs first for every SUT arena: detect language/build system, declared ports,
base runtime, and read the README. Its output feeds the buildpack selector, the
Dockerfile synthesiser, **and** the HITL setup-proposer (`setup_proposer.py`) — so a
proposal is grounded in the actual repo, not guessed. This is the single highest-
leverage fix for the generator's stated top-priority use case.

**Also:** wire `service.package` install (named TODO); ungate build-from-source
safely (was `NIDAVELLIR_ALLOW_SOURCE_BUILD`) behind the verified-loop + egress-during-
build-only + arena-labeled-image-reclaim guardrails already present; version-pin
every produced image; keep the operator-scripted / HITL paths as the fallback/repair
loop when a build can't be made green automatically.

**Acceptance.** A corpus of ~20 diverse public repos: the buildpack-detectable
majority stand up to a health-checked service with **no manual step**; the remainder
via a single verified LLM Dockerfile; every arena rebuilds byte-for-byte from its
pinned spec; a repo that genuinely can't build fails with a clear, phase-tagged
error, not a stuck arena. → **ADR-0008 (build pipeline / repo→image).**

---

### 🔴 M2 — Deep monitoring + crash oracle + structured scoring · **L**

**Goal.** A target with **no pre-known vulnerability manifest is still scorable** —
"the agent made it fall over" is first-class evidence. This is the capability that
separates a demo from something that covers real-world issues, and it's currently
unbuilt (Phase 4).

**Monitor sidecar** around the service-under-test → `events` + the defender feed:
logs, crashes/panics, **sanitizer aborts** (ASan/UBSan when built with them),
unhandled 5xx, resource exhaustion, optional coverage. Model on **OSS-Fuzz /
ClusterFuzz** — a crash or sanitizer abort is a scored signal.

**Deterministic validators, not vibes.** Adopt the **XBOW / Project-Naptime "perfect
verification"** principle: a finding is accepted only when programmatically
confirmed — headless-browser confirmation that an XSS payload executed, an OAST/SSRF
out-of-band callback, an ASan trigger for a memory bug, a DB-state check. Model the
target-condition graders on **CVE-Bench**'s 8 standardized attack-outcome monitors.

**Structured, machine-parseable verdicts.** Emit an **Inspect-style `Score`** (value
∈ binary | numeric | categorical, plus `answer`, `explanation`, `evidence`,
`metadata`) — never free text. Deterministic checks first, LLM-as-judge (majority
vote) only where unavoidable, always JSON.

**Partial credit, not win/lose.** Grade **subtask/milestone progress** (Cybench
ordered subtasks; AutoPenBench Command/Stage Milestones → a **Progress Rate even on
failed runs**), so weak and strong agents are distinguishable and hard targets stay
informative.

**Two scoring modes:** *discovery* (no manifest — monitor signals + operator-triaged
self-reported findings) and *benchmark* (pin a version with a CVE manifest → score
CVE-rediscovery). Per-run metrics: vulns found, crashes/distinct fault sites induced,
milestones reached, steps, wall-clock, tokens, cost.

**Acceptance.** An agent run yields a structured JSON scored report; a crash induced
on a no-manifest target scores; an XSS is only credited after headless-browser
confirmation; a failed run still reports a Progress Rate. → **ADR-0009 (scoring,
validators & eval).**

---

### 🟠 M3 — Benchmark & eval layer · **M**

**Goal.** Every arena run is a comparable, replayable, exportable eval — arenas
double as reproducible agent benchmarks.

**Report the whole tuple, not just a score.** The strongest convergent lesson across
METR, UK-AISI, HAL and SWE-bench's standardized-scaffold track: a published number
conflates model capability with what the **scaffold** allowed. Since agents are
bring-your-own over MCP, **scaffold is a first-class row field** — record
`model + version + harness/scaffold + stance + task-set + score + steps + cost +
pass@k`. Ship an optional **reference harness** (thin Claude/Anthropic-SDK MCP loop)
for apples-to-apples runs.

**Difficulty & anti-saturation.** Attach a difficulty tier and a **First-Solve-Time**
estimate (Cybench's objective human-anchored axis) to each arena; report the hardest
tier an agent cleared. Offer **guided vs unguided** modes (hints/subtasks vs
flag-only) so hard arenas stay informative at 0% unguided solve rate. Keep a
**held-out / non-public** set (3CB / NYU dev-split practice) to resist contamination.

**Trace → dataset (traces you already write become evals).** Align the JSONL trace
schema to **OpenTelemetry GenAI** semantic conventions + **OpenInference** span kinds
(`execute_tool`, `invoke_agent`, `gen_ai.*`, `gen_ai.conversation.id`) so traces flow
into Langfuse/Phoenix/Braintrust unmodified. Adopt the convergent dataset record
shape — `input` / `expected_output` / `metadata` / `tags` + a `source_trace_id`
back-link — and make any span one-click promotable to a dataset item.

**Deterministic replay.** Checkpoint arena + run state so a run can be **replayed or
forked** (LangGraph time-travel; Inspect's compact `.eval` transcript is the model).

**Technique tagging.** Tag every agent action and finding with **MITRE ATT&CK**
(infra), **MITRE ATLAS** + **OWASP LLM Top 10** (AI targets) IDs — the shared
substrate that makes coverage legible to security teams and paired red/blue telemetry
joinable (M7).

**Acceptance.** Two BYO agents on one benchmark arena produce comparable rows
(incl. scaffold + cost + pass@k); a completed run replays deterministically from its
trace; a run exports as a ready-to-use eval dataset.

---

### 🟢 M4 — MCP gateway hardening & multi-agent · **M–L**

**Goal.** Make the seam agents connect through production-grade, and unlock
concurrent multi-stance (the red-vs-blue story).

**MCP-native auth.** Add an **OAuth 2.1** path (MCP 2025-11-25): the gateway as a
Resource Server with RFC 9728 Protected-Resource-Metadata, RFC 8707 **audience-bound
tokens** (`resource` param), PKCE, and an explicit ban on **token passthrough**.
Keep API-key for local/simple use. Speak stdio + **Streamable HTTP** (retire the
deprecated standalone SSE transport).

**Per-request auth + stance binding → concurrent stances (P2-6).** The current
one-key/one-stance-per-process model blocks red-vs-blue; move auth/stance to
per-request so distinct principals share one arena with paired traces.

**Defend the agent boundary itself.** Treat all tool descriptions and tool *results*
as untrusted (Invariant Labs' tool-poisoning, rug-pull, shadowing, confused-deputy):
pin+hash approved tool definitions to detect redefinition; scan tool results for
injected instructions (the "defender reads attacker-tainted logs" requirement,
generalised); enforce per-client consent. Reference: Docker MCP Gateway / Lasso /
IBM ContextForge patterns.

**Durable, fail-closed guardrails.** Cross-process **budgets** (step/time/token/cost,
auto-reset windows, **fail-closed**), RPM/TPM + max-parallel + runaway-loop
(`max_iterations`) guards, per-command timeout, and a **two-scope kill-switch**
(per-arena **and** per-workspace) that drains in-flight commands, hard-stops, and
flushes traces. Model on LiteLLM-proxy enforcement.

**Complete the attacker toolset to match the field.** `upload/download_file`, plus
higher-level tools as first-class MCP schemas — an **HTTP interception proxy**, a
**headless browser** (doubles as the M2 XSS validator), a **Python/code-exec sandbox**
for PoC development, and **SSH tunnelling** — the primitives every serious offensive
agent (XBOW, Strix, CAI) centres on, layered over the shell.

**Observability + HITL.** Emit OTel-GenAI spans; add an approval queue (MCP
**elicitation** — accept/decline/cancel) for risky tool calls.

**Acceptance.** Red + blue agents run concurrently on one arena with paired,
technique-tagged traces; a CI containment test proves arena nodes can't reach the
internet or cloud metadata; a budget breach fails closed and freezes the arena; the
OAuth flow issues an audience-bound token the gateway validates. → **ADR-0005**
(gateway protocol/stances/guardrails) + **ADR-0010 (MCP OAuth & tool supply-chain).**

---

### 🔵 M5 — Console, browser access & the no-AI human path · **M–L**

**Goal.** Meet the product-quality bar and make good on **AI-centered, never
AI-required** — an arena must be fully drivable by a human with no model.

- **In-browser access (realizes the human path, P7-8).** A web terminal
  (**ttyd/wetty**, Xterm.js) for shell-only footholds; **noVNC + websockify** or
  **Apache Guacamole** (guacd, targets isolated behind the gateway) for GUI/desktop —
  exactly the HTB Pwnbox / TryHackMe AttackBox model, attack box and targets on a
  shared private subnet.
- **SSE live feed (P7-3).** Replace 5s polling with an event stream from the `events`
  table — small change, big feel.
- **Live service-monitor panel (P7-6).** Surface M2's crash/log/health/coverage
  signals; the configurator-consent + HITL-approval prompts in the UI.
- **Information architecture.** Arena-fleet (state-grouped, filterable) → mission-
  control per arena (topology, objectives, live score) → **agent-trace replay** and
  **red-vs-blue** views → read-only **auditor** view.
- **Pack library + persistence (P1-3, P1-7).** Ship a curated set of flagship packs
  with **full / light / mini variants** (the GOAD model); **persist imported /
  generated / SUT packs as reusable registry entries** so operators build a library
  from their own work (today custom/SUT arenas compile-and-deploy inline and vanish).
- **Co-pilot upgrade (read-only tools).** Keep the operator co-pilot advise/assist-
  only and inside the scope boundary, but give it a **read-only tool layer** (MCP
  client to safe range-admin reads: list arenas, status, topology, events) so it can
  actually help *operate*, not just describe. Zero mutation.

**Acceptance.** A human drives an arena end-to-end in the browser with no model in
the loop; live updates arrive via SSE (no polling); an operator saves a generated
arena as a reusable pack and relaunches it; the co-pilot answers "what's the state of
arena X?" from live reads.

---

### 🟣 M6 — LLM-application-as-target arenas · **M**

**Goal.** A new arena archetype where the **victim is an LLM application** — the
category with the strongest AppSec/AI-security pull, and naturally container-shaped
(cheap on docker-local). Packs map to **OWASP Top 10 for LLM Apps (2025)** and the
**OWASP Top 10 for Agentic Applications (ASI01–ASI10, Dec 2025)**.

Ship, in order of signal-per-effort:
- **Prompt-injection RAG** (LLM01) — injectable document store; objective: exfiltrate
  a planted secret via indirect injection.
- **System-prompt leakage** (LLM07) and **sensitive-info disclosure** (LLM02).
- **Improper output handling** (LLM05) — model output → XSS/SSRF/RCE downstream
  (**this is where M1's SUT provisioning + M2's validators shine**).
- **Excessive agency / tool abuse** (LLM06 / ASI02) — an agent wired to real tools;
  objective: an unauthorized action.
- **Vector/embedding RAG attacks** (LLM08); **unbounded consumption** (LLM10).

Verdicts are machine-checkable from the app's own logs (reuse M2). Integrate
**garak** (probes+detectors), **PyRIT** (Crescendo/TAP orchestrators), and
**promptfoo** strategies as reference attacker tooling — never as "our AI." The
**MITM stance becomes uniquely valuable here**: memory/context poisoning (ASI06),
inter-agent communication poisoning (ASI07), agent goal hijack (ASI01).

**Acceptance.** One prompt-injection RAG lab scored end-to-end (secret-exfil
detected from app logs); one agentic pack demonstrates MITM inter-agent poisoning
with a scored verdict.

---

### 🟤 M7 — Purple-team paired telemetry & detection scoring · **M**

**Goal.** The red-vs-blue flywheel: attacker and defender on one arena, producing
paired data that's the platform's most defensible dataset.

- **Complete the defender stance:** `get_alerts`, `submit_detection`, response
  actions; sensor webhook → `events`.
- **Detection scoring:** a `detection` objective scores when a blue alert matches a
  red action within a window; a "noisiness" score against the attacker.
- **Asymmetric scoring:** weight **remediation/patch above detection** (DARPA AIxCC
  weighted patching 3× over finding; CyberSecEval v4 AutoPatch) — reward fixing, not
  just spotting.
- **Joinable paired dataset:** ATT&CK-tag both sides (M3) and join into a purple-team
  eval set — the **Caldera GameBoard** (paired red/blue scored TP/FP/TN/FN) and
  **VECTR** (technique-tagged detection-coverage heatmaps) model.
- **Optional adversary-emulation baselines:** **MITRE CALDERA** + **Atomic Red Team**
  (~1,800 ATT&CK-mapped tests) as a deterministic non-AI red baseline to calibrate
  detection scoring.

**Acceptance.** A concurrent red-vs-blue run yields a joined, ATT&CK-tagged paired
dataset with both detection and remediation scores; a CALDERA baseline run produces
comparable detection coverage.

---

### ⚫ M8 — Hardening & multi-provider hosting · **L**

**Goal.** Run as a hosted, multi-tenant platform on real infra — deferred until the
M1–M3 spine is compelling.

- **Ownership/RBAC + quotas + workspaces + SSO.** Per-operator identity (fixes D2),
  least-privilege bootstrap key (D3), team workspaces as the tenancy boundary,
  **Google OAuth2 SSO** for the console (MCP path stays API-key/OAuth per M4),
  graduated RBAC (auditor/operator/admin/owner), **envelope custody** for the BYO-AI
  key (ciphertext the control plane can't itself decrypt).
- **Isolation hardening.** Get `docker.sock` **off the orchestrator** (root-
  equivalent today) — route exec through the worker or a socket-proxy/rootless
  daemon; per-agent container sandbox with CPU/mem caps + filesystem-off-by-default
  (K8s Sandbox CRD pattern).
- **Real VM/cloud apply.** libvirt live boot; **AWS** apply (VPC-per-arena, no NAT by
  default, SSM, everything tagged `nidavellir:arena_id`); adopt a **Ludus-style
  ranges-as-code** layer (single YAML → multi-VM/VLAN, snapshot + internet-cut +
  rollback "testing mode") for multi-machine VM arenas. **VulnHub VM converter**
  lands here (needs the VM backend).
- **Observability & scale (P6).** OTel + Prometheus/Grafana; structured JSON logs
  with `arena_id` correlation; `/healthz` vs `/readyz`; worker graceful shutdown +
  retry; cost guardrails (TTL reaper + quotas + AWS Budgets alarm + orphan sweep).

**Acceptance.** An arena deploys on AWS from the hosted control plane behind
TLS + SSO; teardown leaves zero tagged resources; two operators can't touch each
other's arenas; budget alarm + orphan sweep verified in a game-day. → **ADR-0006
(AWS topology & cost controls).**

---

## 4. Standing principles (every milestone honours these)

- **Scope boundary (load-bearing).** Nidavellir builds the **integration surface and
  the safe substrate only** — the MCP connectors, validated schemas, provider
  compiler, sandbox, monitor, consent gate, scoring engine, trace store. **The AI is
  always bring-your-own**, under the user's own key and model. We ship no AI
  attacker, defender, judge, or generator; reference harnesses/connectors are thin,
  optional wiring samples. When a model configures a SUT service it is BYO AI
  exercising a gated capability, never "Nidavellir's AI." (`cyberguard-ai-scope-boundary`)
- **AI-centered, never AI-required.** Built for testing AI agents and MCP-compliant
  throughout, but **no arena may depend on a model** — every arena stays fully
  drivable by a human (browser/terminal/console + manual finding submission, M5).
  (`cyberguard-ai-optional`)
- **Containment is the primary control.** Arena segments have **no egress** by
  default (provider-enforced), + optionally an allowlisted apt/pip mirror; a CI
  containment test proves an arena node can't reach an external canary or cloud
  metadata. Never-auto-deploy generated infra; consent-gated, HITL-approved, time-
  boxed configurator with a hard privilege boundary.
- **Correctness & security before features.** Every milestone: `make check` green;
  new behaviour has tests + a regression test for bug fixes; no new bare `except:`;
  no secrets in code/logs/fixtures; architecturally significant decisions get an ADR;
  user-facing changes update `docs/`.
- **Verify the product, not the tests.** "Green pytest against an explicit provider"
  is not "works through the stack" — live-verify through the actual compose product.
  (`cyberguard-verify-the-product-not-tests`)

---

## 5. State of the art we align to (references)

Design patterns and tools this roadmap deliberately adopts, so we build on the
field's best practice instead of reinventing it. (Vendor performance figures are
self-reported; treat as directional.)

**Repo → runnable image (M1)**
- Cloud Native Buildpacks / Paketo — deterministic detect→build→export · https://buildpacks.io · https://paketo.io
- Railpack (Nixpacks successor, maintained) · https://github.com/railwayapp/railpack
- Dev Containers spec (`devcontainer.json`, CLI) · https://containers.dev
- Repo2Run — LLM Dockerfile synthesis w/ verified-build + rollback (~86%) · https://arxiv.org/abs/2502.13681
- BuildKit git-context builds; Depot remote cached builders · https://docs.docker.com/build/concepts/context/

**Monitoring, validators & scoring (M2–M3)**
- OSS-Fuzz / ClusterFuzz + sanitizers — crash/abort as evidence · https://google.github.io/oss-fuzz/
- XBOW deterministic validators; Project Naptime "perfect verification" · https://xbow.com/blog/core-components-ai-pentesting-framework · https://projectzero.google/2024/06/project-naptime.html
- Cybench (subtasks, guided/unguided, First-Solve-Time) · https://cybench.github.io · https://arxiv.org/abs/2408.08926
- CVE-Bench (8 standardized attack-outcome graders) · https://arxiv.org/abs/2503.17332
- AutoPenBench (Command/Stage milestones → Progress Rate) · https://arxiv.org/abs/2410.03225
- UK-AISI Inspect (`Score`, Solver/Scorer, `.eval` transcripts) · https://inspect.aisi.org.uk
- METR Task Standard (`score()→float|None`, network-permission gating) · https://github.com/METR/task-standard
- Meta CyberSecEval v3/v4 (ATT&CK mapping, FRR, AutoPatch, CyberSOCEval) · https://github.com/meta-llama/PurpleLlama
- Reporting model+scaffold+cost+pass@k — HAL / AISI elicitation-disclosure / SWE-bench standardized-scaffold · https://arxiv.org/abs/2510.11977

**MCP, gateway & tracing (M4)**
- MCP spec 2025-11-25 (transports, OAuth 2.1, elicitation, security best-practices) · https://modelcontextprotocol.io
- MCP threat classes — tool poisoning / rug-pull / confused-deputy · https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks
- Gateways: Docker MCP Gateway · https://docs.docker.com/ai/mcp-gateway/ · IBM ContextForge · https://github.com/IBM/mcp-context-forge · Lasso · https://github.com/lasso-security/mcp-gateway
- OpenTelemetry GenAI semconv + OpenInference span kinds · https://opentelemetry.io/docs/specs/semconv/gen-ai/ · https://github.com/Arize-ai/openinference
- Trace→dataset: Langfuse / Braintrust (`input`/`expected`/`metadata`/`source_trace_id`) · https://langfuse.com/docs/evaluation/experiments/datasets
- Budget/rate/egress fail-closed enforcement — LiteLLM Proxy · https://docs.litellm.ai/docs/proxy/users
- Offensive-agent toolsets — XBOW · Strix (Graph of Agents) https://github.com/usestrix/strix · CAI https://github.com/aliasrobotics/cai · PentestGPT https://github.com/GreyDGL/PentestGPT

**LLM-app targets & purple-team (M6–M7)**
- OWASP Top 10 for LLM Apps 2025 · https://genai.owasp.org/llm-top-10/
- OWASP Top 10 for Agentic Applications (ASI01–10) + Threats T1–T15 · https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/
- garak · https://github.com/NVIDIA/garak · PyRIT · https://github.com/microsoft/PyRIT · promptfoo · https://www.promptfoo.dev/docs/red-team/
- AgentDojo (indirect-injection agent-security benchmark) · https://arxiv.org/abs/2406.13352
- MITRE CALDERA + GameBoard (paired red/blue) · https://github.com/mitre/caldera · Atomic Red Team · https://github.com/redcanaryco/atomic-red-team · VECTR · https://github.com/SecurityRiskAdvisors/VECTR
- MITRE ATLAS (AI ATT&CK) · https://atlas.mitre.org/

**Ranges & access (M5, M8)**
- GOAD (data-defined AD labs, variants) · https://github.com/Orange-Cyberdefense/GOAD
- Ludus (ranges-as-code, snapshot/rollback/isolation) · https://docs.ludus.cloud
- Vulhub (compose CVE envs) · https://github.com/vulhub/vulhub · DVWA · Juice Shop · Metasploitable
- Browser access — Apache Guacamole · https://guacamole.apache.org · noVNC · https://github.com/novnc/noVNC · ttyd

---

## 6. Architecture decision records

- **0002** auth model (roles admin/operator/agent) — Accepted
- **0003** provider driver interface & scenario compilation — Accepted
- **0004** datastore: PostgreSQL + Alembic — Accepted
- **0005** MCP agent gateway protocol, stances & guardrails — to finalise (M4)
- **0006** AWS deployment topology & cost controls — to write (M8)
- **0007** software-under-test arenas (provisioner, gated configurator, monitoring/
  crash-oracle, discovery-vs-CVE scoring) — Proposed (M1/M2)
- **0008** repo→image build pipeline (deterministic-first + verified LLM synthesis) — Proposed (M1; tier-1 Dockerfile landed)
- **0009** scoring, deterministic validators & trace→eval dataset format — to write (M2/M3)
- **0010** MCP OAuth 2.1 & tool supply-chain defenses — to write (M4)

---

*Re-sequenced 2026-07-01 around the software-under-test vertical (M1–M3 spine) and
aligned to the 2025–2026 state of the art in agent benchmarks, offensive-AI tooling,
repo→image build systems, MCP security, and agent trace/eval infrastructure. Revisit
at the end of each milestone and amend via PR. North star: `.agent/proposals/VISION.md`.*
