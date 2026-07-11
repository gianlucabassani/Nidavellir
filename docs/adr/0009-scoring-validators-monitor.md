# ADR-0009: Monitoring, deterministic validators & structured scoring

- **Status:** Proposed (ROADMAP M2; the monitor sidecar / crash oracle landed —
  deterministic validators and the structured scored verdict are the remaining
  M2 items 6–7)
- **Date:** 2026-07-11
- **Deciders:** Gianluca Bassani

## Context

M1 makes *provisioning* any repo reliable. M2 must make the *result* scorable —
including for a target with **no known-vulnerability manifest**, which the CTF/
manifest model (ADR-0007, findings-vs-manifest) cannot score. The convergent
lesson from OSS-Fuzz / ClusterFuzz, XBOW's validators, CVE-Bench's attack-outcome
graders, and UK-AISI Inspect's `Score` is: treat an observed fault (a crash, a
sanitizer abort, a programmatically-confirmed exploit) as first-class evidence,
and emit a structured, machine-parseable verdict — never free text.

The arena already has the substrate this rides on: an append-only `events` audit
table (ADR-0004), a provider interface with read-only introspection hooks
(ADR-0003), and a defender feed that reads events (`query_events`). So the monitor
is a new provider capability + a periodic sweep + a new event type, not a new
subsystem.

## Decision

We will build M2 in three parts against the existing events/provider substrate.
**This increment lands part 1 (the monitor / crash oracle); parts 2–3 are
specified here and follow.**

1. **Monitor sidecar / crash oracle (landed).** A pure detector
   `monitor.detect_signals(observations)` turns per-node runtime observations
   (container state + a bounded log tail) into structured signals:
   `crash`, `sanitizer_abort`, `unhandled_5xx`, `resource_exhaustion`, each with
   `{kind, node, severity, summary, evidence, key}`. A provider capability
   `collect_monitor_signals(instance_id)` gathers the observations (docker-local:
   container `State` + `RestartCount` + log tail for the SUT nodes, skipping the
   attacker foothold and arena infra; mock: empty; VM/cloud: refuse cleanly). A
   Celery-beat task `monitor_arenas` polls every ACTIVE arena, runs the detector,
   and appends each **new** signal (dedup by `key`) to `events` as
   `monitor_signal` (`actor: "monitor"`) — which the defender stance and operator
   console already surface. The deterministic **state** signals (non-zero exit,
   OOM-kill, crash-loop) are authoritative; the **log** heuristics are
   conservative best-effort that add coverage without pretending to be exhaustive.

2. **Deterministic validators (M2 item 6, to build).** A finding is credited only
   when programmatically confirmed: headless-browser confirmation an XSS payload
   executed, an OAST/SSRF out-of-band callback, an ASan trigger for a memory bug, a
   DB-state check. Modeled on XBOW / Project Naptime "perfect verification" and
   CVE-Bench's standardized attack-outcome monitors. The headless-browser XSS
   validator is shared with M4's headless-browser tool (build once).

3. **Structured scored verdict (M2 item 7, to build).** An Inspect-style `Score`
   (value ∈ binary | numeric | categorical, plus `answer`, `explanation`,
   `evidence`, `metadata`) — never free text. Subtask/milestone **partial credit**
   (a Progress Rate even on failed runs, per Cybench / AutoPenBench) and two modes:
   *discovery* (monitor signals + operator-triaged self-reported findings) and
   *benchmark* (pin a version with a CVE manifest → score CVE-rediscovery).

## Alternatives considered

- **A true persistent sidecar container per arena** — continuous, but heavier
  (one long-lived container + log-shipping per arena) and harder to make
  deterministic/testable. Rejected for now: a bounded periodic poll reuses the
  proven reaper pattern, is pure-testable, and is enough at M2. Revisit if
  sub-second crash latency or coverage tracing is needed.
- **LLM-as-judge for every verdict** — non-deterministic and gameable. Rejected as
  the default; reserved (majority-vote, JSON-only) for the narrow cases the
  deterministic validators can't cover.
- **Extend the manifest/findings model only** — cannot score a no-manifest target,
  which is the whole M2 unlock.

## Consequences

- Positive: a crash / sanitizer abort on any ACTIVE arena is now recorded evidence,
  visible to the defender feed and operator console, with stable dedup — the input
  the scorer (item 7) consumes. No new endpoint, no migration (event-backed).
- Positive: pure detector + provider seam keeps it unit-testable offline and
  provider-agnostic (docker-local now; VM/cloud refuse cleanly until M8).
- Negative / cost: log heuristics are best-effort and can miss or (rarely)
  mis-tag; the deterministic state signals are the reliable core, and item 6's
  validators are what gate *credited* findings. A busy target's log tail is
  bounded, so a fault that scrolled far past the tail between ticks can be missed
  (mitigated by the 30s default interval; tune `NIDAVELLIR_MONITOR_INTERVAL_SECONDS`).
- Follow-ups: M2 items 6 (validators) and 7 (scored verdict + partial credit) fill
  in the rest of this ADR; M3 exports the resulting run as an eval dataset.
