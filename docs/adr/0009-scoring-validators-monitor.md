# ADR-0009: Monitoring, deterministic validators & structured scoring

- **Status:** Accepted (ROADMAP M2 complete — monitor/crash oracle, deterministic
  validators, and the structured scored verdict with partial credit all landed)
- **Date:** 2026-07-11 (updated 2026-07-13: items 6–7 shipped;
  amended 2026-09-24 for NV-06 effect-confirmed scoring)
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

We build M2 in three parts against the existing events/provider substrate.
**All three have now landed** (part 1: `monitor.py`; part 2: `validators.py`;
part 3: `scoring.py`, wired into `POST /arenas/{id}/findings` and
`GET /arenas/{id}/score`).

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

2. **Deterministic validators (M2 item 6, landed — `validators.py`).** A finding is
   *confirmed* only when programmatically verified, never on the agent's say-so
   (XBOW / Project-Naptime "perfect verification"; CVE-Bench attack-outcome
   monitors). Verification is deterministic — no LLM. Two families:
   **active** validators run at finding-report time and observe the effect
   (`reflected_xss`: a platform-owned nonce payload must execute in the
   arena-scoped headless browser and write its marker into the rendered DOM;
   `marker`: a planted secret disclosed by injection; `oast_callback`: an
   out-of-band callback); **passive** `correlate_crash` ties a finding to a
   crash-oracle signal on its node (the no-manifest credit path). The effect
   functions are injected, so the module is pure/offline-testable; the API binds
   HTTP/browser probes **fixed to the arena's own victim** (path + params only,
   never an arbitrary host — a validator can't become an SSRF primitive), backed
   by a foothold `curl` or arena-network browser. `confirmed` is **tri-state**:
   `True` (verified), `False`
   (refuted — probe ran, effect absent), `None` (unknown — no applicable validator
   or the probe couldn't run). `None` never credits *or* discredits; only `True`
   earns confirmed credit. The verification verdict is operator-only — redacted from
   the agent's event feed alongside `matched_vuln_id`, so the neutral ack can't leak
   whether the exploit worked.

3. **Structured scored verdict (M2 item 7, landed — `scoring.py`).** `score_arena()`
   emits an Inspect-style `Score` (`value` ∈ binary | numeric | categorical, plus
   `answer`, `explanation`, `evidence`, `metadata`) — never free text. Two modes,
   auto-selected by manifest presence (operator-overridable via `?mode=`):
   *benchmark* (CVE-rediscovery against the pinned manifest — `found` matched by
   CWE+node, `confirmed` the validator-verified subset, points + confirmed-points)
   and *discovery* (no manifest — distinct crash-oracle **fault sites** + confirmed
   findings drive the score). **Partial credit / Progress Rate**: an ordered
   milestone ladder (foothold → recon → first blood → verified exploit → full clear,
   per Cybench / AutoPenBench) scores even a failed run, so a weak agent build is
   distinguishable from a strong one. Per-run metrics (steps, wall-clock; token/cost
   when announced) ride in `metadata`. The pre-M2 scorecard keys stay flat and
   backward-compatible.

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
- Positive (items 6–7): a finding is now credited on *proof*, not the agent's
  claim, and the arena emits one machine-parseable verdict per run — the exact
  record M3 promotes into an eval dataset. Discovery mode + the milestone ladder
  mean a no-manifest SUT arena and a failed run are both still scorable.
- Negative / cost (items 6–7): active validation is best-effort — it needs a
  reachable victim web port and the relevant probe runtime, and degrades to
  `confirmed: null` (unverified) otherwise, so "unverified" ≠ "not vulnerable".
  Reflected XSS uses the M4 headless browser as its authoritative execution oracle.
  Token/cost
  metrics are only as good as what the agent announces.
- Follow-ups: M3 exports the scored run (OpenInference-aligned trace → dataset) and
  ships the reference harness.

## NV-06 amendment — independent effects and controls (2026-09-24)

The earlier tri-state `confirmed` projection remains for API compatibility.
New verdicts use `nidavellir/validation-verdict/v1` with `confirmed`,
`refuted`, `inconclusive` and `infrastructure_failure`, a stable reason code,
validator version, pinned recipe and target identity, linked action digest,
target observation and healthy-control digests, and timestamp. The operator-only
finding event stores those references. Target-local observations live in an
arena-scoped, integrity-checked content-addressed store and remain reviewable
after teardown. Agent acknowledgements stay neutral; the agent event feed
removes manual verification events and redacts match and automatic verdicts.

The first class-specific adapter validates an A-to-B object authorization
effect against a private target-local read-back and a B-to-B healthy control.
The image, seed and truth are pinned in the lifecycle recipe; reset returns to
an empty effect log. A participant's HTTP transaction establishes the action
link. A matching response body, CWE, marker or PoC alone earns no credit. The
marker validator now requires the operator-owned manifest marker. Passive
crash correlation requires a linked action timestamp followed within 120
seconds by a same-node signal. An unavailable probe is an infrastructure
failure, distinct from a successful probe that refutes the claim.

Benchmark `found` and `points_earned` still describe claim coverage.
Headline `Score.value`, `confirmed_points`, `verified_exploit` and full
clear require independent automatic confirmation. Discovery retains observed
fault sites but credits a linked, confirmed finding; it has no full-clear
ground-truth denominator. Operator confirmation requires an existing immutable
evidence digest and is reported in `manual_confirmed` separately from
automatic credit. A manual refutation disqualifies a claim while preserving
the original automatic verdict in the append-only event history. The score
declares `nidavellir/effect-confirmed/v1` semantics.

This amendment tightens the M2 decision without changing the event, provider,
operator/agent or eval-export boundaries. It does not claim general validators
for all vulnerability classes or live cloud/VM support.
