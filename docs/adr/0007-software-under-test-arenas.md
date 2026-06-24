# ADR-0007: Software-under-test (SUT) arenas — provision, configure, monitor, score any OSS project

- **Status:** Proposed
- **Date:** 2026-06-18
- **Deciders:** Gianluca Bassani

## Context

Nidavellir's arenas today run **pre-built** victim workloads — a curated catalog
image (DVWA, Juice Shop, …) or a fixed scenario pack. A high-value use case is the
opposite: point the platform at *an arbitrary open-source project* and have a
bring-your-own agent pentest it — find real bugs in real software, **white-box**
(source available) or **black-box** (only the running service).

Four forces make this more than "add another image":

1. **Provisioning.** An OSS target is a *repo at a ref* (or a package, or an
   image you must build), not a published catalog tag. It must be built and
   **pinned** for reproducibility — and, where a trustworthy published image
   already exists, that image should be preferred over a from-source build.
2. **Configuration.** Standing an arbitrary service up usually needs real setup
   (env, DB, migrations, seed data, build flags), and should follow the project's
   own documented instructions. Sometimes a human can script it; sometimes it's
   faster to let the *model* configure it — but giving an AI write/config access to
   a node is a privilege escalation that must be a deliberate, revocable operator
   choice, not a default.
3. **Scoring without a manifest.** The known-vulnerability manifest model
   (ADR-0005 / report_finding) assumes the operator already knows the planted
   bugs. For a fresh OSS target there may be *no* manifest — yet "the agent made
   the service crash" is still a real, scorable result.
4. **Human-without-AI usability.** Nidavellir is AI-centered and MCP/agent-compliant,
   but it must **not require** an agent: a human pentester must be able to operate
   any arena — including a SUT arena — against a static vulnerable target with no
   model in the loop. The SUT machinery (provisioner, monitor, attacker-node access)
   serves the human path first; the agent stances layer on top.

The data-defined topology engine (ADR-0003, scenario schema v3), egress
containment + package mirror, the MCP gateway/stances (ADR-0005), and the
append-only `events` spine (ADR-0004) already exist. The goal is to add the SUT
archetype as **composable capabilities on top of that substrate**, not a parallel
engine — so new target *kinds* stay config, not code.

This archetype is **distinct from, and complementary to, growing the curated image
catalog** — including a deterministic **auto-converter from public sources like
VulnHub** (ROADMAP P1-5). That track keeps expanding a library of known,
ready-to-run targets; SUT provisioning handles the *arbitrary OSS project* case.
Both are still needed; neither subsumes the other.

## Decision

We will support **software-under-test arenas** via the following, fronted by an
**arena wizard** (the dynamically-configurable, scalable setup surface):

1. **Service provisioner — packaged-first, build only for gaps.** A node may
   declare a `service:` block: an `image`/container (**preferred**), a `package`,
   or `source` (git repo + ref + build / Dockerfile / compose). Resolution policy:
   - **Black-box** targets **prefer an existing, user-approved packaged image or
     container**; the compiler builds from source **only** when no published image
     exists or the user hasn't approved one. This avoids version/build **mismatch**
     (testing what the operator thinks they're testing) and keeps black-box runs
     reproducible and trustworthy.
   - **White-box** targets **require the source**, built and configured **per the
     project's own (e.g. GitHub) build/run instructions**. The agent gets a vantage
     *above* the victim — it reads the mounted source — while it **dynamically
     tests the running service from the attacker node** (or wherever it prefers).
   Everything is **version-pinned**; docker-local first. Adding a target = a
   validated `service:` block, no code.
2. **Gated setup / configurator capability** — per arena the operator picks how
   the service is brought up: **operator-scripted**, **human-in-the-loop** (the
   agent proposes setup steps; the operator approves each), or **autonomous
   opt-in** (a short-lived *configurator* role with write/config tools on the
   victim node, dropped to the attacker stance before the engagement). Setup
   follows the project's documented instructions. Granting write/config or autonomy
   **requires explicit operator consent** captured in the wizard; the default is
   operator-scripted / HITL.

   **Confirmed design (2026-06-18).** The configurator is a **4th, special stance**
   (time-boxed, **victim-scoped**, write-capable, revoked before the engagement),
   adding an explicit arena **setup phase** (`provisioning → setup → ready →
   engagement`). Decided forks:
   - **Build order:** ship **operator-scripted + HITL first**; **autonomous-opt-in**
     comes later behind a **double lock** — a platform flag
     (`NIDAVELLIR_ALLOW_AUTONOMOUS_CONFIGURATOR=true`) **and** explicit per-arena
     operator consent (defense in depth for the most dangerous mode).
   - **Privilege boundary = HARD:** the configurator and the attacker are **separate
     sessions/keys** — the attacker key never holds write/config; at
     `finish_setup`/time-box expiry the configurator is revoked and the engagement
     runs under the attacker stance. Not a same-session stance transition (avoids
     lingering write privilege). Falls out naturally from the current
     one-stance-per-process gateway.
   - **Setup egress = opt-in OPEN:** during setup the victim may be granted open
     egress (parallel to build-from-source), behind an explicit per-arena opt-in;
     the arena **runtime stays egress-locked** regardless.
   - **Enforcement point = the orchestrator** (consent + victim-scope + time-box +
     step/command budget); the gateway only exposes the configurator toolset for
     `stance=configurator`. State via a `setup_session`/`setup_step` event model
     (reuse `events`, no migration). Every consent/proposal/approval/exec/revocation
     is audited. The **operator-scripted** mode is the **AI-optional human path**.
3. **Deep monitoring + crash oracle** — a monitor sidecar around the SUT streams
   logs, process crashes/panics, sanitizer aborts, unhandled 5xx, and resource
   exhaustion into `events` and the defender feed. A crash / sanitizer abort /
   unhandled-5xx is a **first-class evidence signal**.
4. **Two scoring modes** — *discovery* (no manifest: monitor signals +
   self-reported findings, operator triages) and *benchmark* (pin a version with
   known CVEs + a manifest → score CVE-rediscovery per model + version + harness).
5. **No-AI / human-attacker path is first-class.** Every SUT arena must be fully
   operable by a **human pentester with no agent in the loop**: the attacker node is
   reachable (browser / SSH / console), the target is up and monitored, and scoring
   (discovery findings, the crash oracle, a CVE manifest) works whether the actor is
   a human or an agent. The MCP gateway/stances are an *additional* way in, never the
   only one.

The **scope boundary holds**: when the model configures or tests the service it is
still bring-your-own AI under the operator's key, exercising a capability
Nidavellir *provides and gates*. Nidavellir ships the provisioner, the sandbox
(egress lockdown), the monitor, and the consent gate — never the AI.

The **arena wizard and monitor UI live in the current console, which is a temporary
surface.** The planned console rework (ROADMAP Phase 7) must be modular and modern
and keep a **persistent communication link with whatever model is connected** (the
connected-model chip is the seed of this) — while the **human-only path must keep
working with no model link at all**.

## Alternatives considered

- **Just add more catalog images.** Doesn't scale to "any OSS project" and can't
  test a specific repo/commit; no build-from-source, no white-box. (Still worth
  doing as a *separate* track — the VulnHub auto-converter, P1-5 — but not a
  substitute for SUT provisioning.)
- **Always build from source, even when a packaged image exists.** Slower, more
  fragile, and risks a **version/build mismatch** between what the operator thinks
  they're testing and what actually runs. We prefer an approved packaged image for
  black-box and build only to fill gaps.
- **AI-only — require an agent to drive an arena.** Rejected: the platform is
  AI-centered but **not AI-required**; a human attacker must be able to use any
  arena against a static target with no model in the loop.
- **Always let the agent configure the service (no gate).** Simplest, but hands an
  untrusted model write/config on a node by default — unacceptable; the consent
  gate + HITL path is the whole point.
- **Reuse the attacker stance for setup.** The attacker stance is intentionally
  foothold-scoped and read-mostly; setup needs broader, write-capable, *victim-node*
  access. Conflating them would widen the attacker stance's blast radius. A
  separate, time-boxed configurator role keeps the engagement stance tight.
- **Require a manifest for every arena (extend ADR-0005 only).** Excludes fresh
  targets with unknown bugs — exactly the use case. The crash oracle lets
  discovery mode score without ground truth.

## Consequences

- **Positive:** any OSS project becomes an arena from a wizard; white/black-box and
  the configure-role are explicit, consented choices; black-box defaults to a
  trusted, approved image (less mismatch/build risk) while white-box gives a
  source-reading vantage + dynamic testing; targets with no known bugs are still
  scorable via the crash oracle; pinned versions + CVE manifests turn OSS targets
  into reproducible agent benchmarks; **human pentesters can run any arena with no
  AI**; everything stays container-first, TTL-reaped, and parallelizable at scale.
- **Negative / cost:** building arbitrary repos is slower and riskier than pulling
  an image (build sandboxing, cache, timeouts); **packaged-first needs an image
  approval/allowlist** concept + a source-fallback decision; following a project's
  arbitrary build instructions must be sandboxed; the configurator role is a new
  privilege surface (scope, time-box, audit); the monitor sidecar and crash-oracle
  add per-arena moving parts; discovery-mode scoring needs operator triage (it is
  assistive, not a clean oracle).
- **Follow-ups this unlocks or requires:** schema `service:` block + compiler
  support, packaged-first resolution (ROADMAP P1-6); the gated configurator
  capability + white-box source access (P2-10); the arena wizard (P3-3) and its
  console UI + monitor panel (P7-6); monitoring/crash-oracle + evidence/CVE scoring
  (P4-6/P4-7). The curated-catalog + **VulnHub auto-converter (P1-5)** is a separate,
  still-needed track. The **Phase-7 console rework** must be modular/modern, keep a
  **live model-comms link**, and never break the **no-AI human path**. Accept this
  ADR when the provisioner + wizard land with a first OSS target end-to-end.
