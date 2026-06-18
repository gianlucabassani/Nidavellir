# ADR-0007: Software-under-test (SUT) arenas — provision, configure, monitor, score any OSS project

- **Status:** Proposed
- **Date:** 2026-06-18
- **Deciders:** Gianluca Bassani

## Context

CyberGuard's arenas today run **pre-built** victim workloads — a curated catalog
image (DVWA, Juice Shop, …) or a fixed scenario pack. A high-value use case is the
opposite: point the platform at *an arbitrary open-source project* and have a
bring-your-own agent pentest it — find real bugs in real software, **white-box**
(source available) or **black-box** (only the running service).

Three forces make this more than "add another image":

1. **Provisioning.** An OSS target is a *repo at a ref* (or a package, or an
   image you must build), not a published catalog tag. It must be built and
   **pinned** for reproducibility.
2. **Configuration.** Standing an arbitrary service up usually needs real setup
   (env, DB, migrations, seed data, build flags). Sometimes a human can script it;
   sometimes it's faster to let the *model* configure it — but giving an AI
   write/config access to a node is a privilege escalation that must be a
   deliberate, revocable operator choice, not a default.
3. **Scoring without a manifest.** The known-vulnerability manifest model
   (ADR-0005 / report_finding) assumes the operator already knows the planted
   bugs. For a fresh OSS target there may be *no* manifest — yet "the agent made
   the service crash" is still a real, scorable result.

The data-defined topology engine (ADR-0003, scenario schema v3), egress
containment + package mirror, the MCP gateway/stances (ADR-0005), and the
append-only `events` spine (ADR-0004) already exist. The goal is to add the SUT
archetype as **composable capabilities on top of that substrate**, not a parallel
engine — so new target *kinds* stay config, not code.

## Decision

We will support **software-under-test arenas** via four additions, fronted by an
**arena wizard** (the dynamically-configurable, scalable setup surface):

1. **Service provisioner** — a node may declare a `service:` block: `source`
   (git repo + ref + build command / Dockerfile / compose), `image`, or
   `package`. The provider compiler builds and **version-pins** it; docker-local
   first. Adding an OSS target = a validated `service:` block, no code.
2. **Gated setup / configurator capability** — per arena the operator picks how
   the service is brought up: **operator-scripted**, **human-in-the-loop** (the
   agent proposes setup steps; the operator approves each), or **autonomous
   opt-in** (a short-lived *configurator* role with write/config tools on the
   victim node, dropped to the attacker stance before the engagement). Granting
   write/config or autonomy **requires explicit operator consent** captured in the
   wizard; the default is operator-scripted / HITL. White-box arenas additionally
   expose the mounted source to the agent.
3. **Deep monitoring + crash oracle** — a monitor sidecar around the SUT streams
   logs, process crashes/panics, sanitizer aborts, unhandled 5xx, and resource
   exhaustion into `events` and the defender feed. A crash / sanitizer abort /
   unhandled-5xx is a **first-class evidence signal**.
4. **Two scoring modes** — *discovery* (no manifest: monitor signals +
   self-reported findings, operator triages) and *benchmark* (pin a version with
   known CVEs + a manifest → score CVE-rediscovery per model + version + harness).

The **scope boundary holds**: when the model configures or tests the service it is
still bring-your-own AI under the operator's key, exercising a capability
CyberGuard *provides and gates*. CyberGuard ships the provisioner, the sandbox
(egress lockdown), the monitor, and the consent gate — never the AI.

## Alternatives considered

- **Just add more catalog images.** Doesn't scale to "any OSS project" and can't
  test a specific repo/commit; no build-from-source, no white-box.
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
  the configure-role are explicit, consented choices; targets with no known bugs
  are still scorable via the crash oracle; pinned versions + CVE manifests turn
  OSS targets into reproducible agent benchmarks; everything stays container-first,
  TTL-reaped, and parallelizable at scale.
- **Negative / cost:** building arbitrary repos is slower and riskier than pulling
  an image (build sandboxing, cache, timeouts); the configurator role is a new
  privilege surface that must be carefully scoped, time-boxed, and audited; the
  monitor sidecar and crash-oracle add per-arena moving parts; discovery-mode
  scoring needs operator triage (it is assistive, not a clean oracle).
- **Follow-ups this unlocks or requires:** schema `service:` block + compiler
  support (ROADMAP P1-6); the gated configurator capability + white-box source
  access (P2-10); the arena wizard (P3-3) and its console UI + monitor panel
  (P7-6); monitoring/crash-oracle + evidence/CVE scoring (P4-6/P4-7). Accept this
  ADR when the provisioner + wizard land with a first OSS target end-to-end.
