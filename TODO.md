# Nidavellir — ordered delivery checklist

Updated 2026-09-23 after completing the NV-03 confined-PoC gate.
This is the canonical work queue. [ROADMAP.md](ROADMAP.md) retains product scope,
design detail and legacy milestone mapping. Unchecked means unfinished.
Verification history is in [docs/JOURNAL.md](docs/JOURNAL.md).

## Scope and success

Build a professional local research and agent-testing platform: reproduce a target,
give a human/BYO agent a contained research position, independently validate the result,
reset and compare a changed agent or target. Docker-local is the first supported path.
Discovery and evaluation both remain in scope; broader research features follow a
demonstrated target need. Bughunt owns live bounty campaigns and their agent workflow.

## P0 — trustworthy research runtime

- [x] **NV-01 — Reproducible release/test environment.** Pin the supported Python 3.11
  verification environment; fix the Bandit exclusion for nested `venv`; run the full
  lint/security/SQLite and PostgreSQL gates with explicit Docker/Tofu integration skips.
  Add clean-install/migration and API/UI/gateway readiness smoke checks.
  **Accept:** a documented clean-checkout command completes the full gate; record versions,
  counts and skips. The host Python 3.14 TestClient stall is not a passing full suite.
- [x] **NV-02 — Prove target lifecycle and reset reproducibility.** Extend current pinned
  intake with manifests for build inputs, dependencies, runtime platform, configuration,
  seed data and reset strategy; readiness/health, bounded deployment and cleanup recovery.
  Refuse or explicitly label non-reproducible dependencies instead of promising arbitrary
  repo reproducibility. **Depends:** NV-01.
  **Accept:** repeated deploy/reset produces equivalent starting conditions; interrupted
  deploy/destroy leaves no orphan resources; evidence remains readable after teardown.
- [x] **NV-03 — Confined PoC execution.** Worker-owned disposable Python/PoC helpers with
  CPU/RAM/PID/time limits, minimal filesystem and no external egress; explicitly allow only
  required arena targets and transfer paths. Integrate existing HTTP/browser/file primitives
  with the same capability and audit model. Do not expand control-plane Docker authority.
  **Depends:** NV-02. **Accept:** develop/run a local PoC; prove helpers cannot reach the
  host, other arenas, internet or metadata endpoints; stop/error paths reclaim helpers.
- [ ] **NV-04 — Durable budgets and stop controls.** Persist and atomically account action
  and time budgets across gateway reconnects, concurrent calls and worker restart. Token/cost
  accounting uses observable driver data; unsupported enforcement is explicit and budget-
  constrained jobs refuse to start when required accounting is unavailable. Reserve before
  execution and reconcile outcomes. Extend existing binding pause to arena/system stop,
  rejecting new work and cancelling/draining helpers with final traces.
  **Depends:** NV-03. **Accept:** reconnect cannot reset budgets; racing requests cannot
  exceed reservations; stop terminates helpers and does not lose evidence or final state.
- [ ] **NV-05 — Scoped research access and runtime capabilities.** Add foothold-scoped
  forwards only for the selected research workflow: explicit destination, expiry, cleanup,
  binding and audit. Publish a bounded REST/GUI/MCP manifest for supported operations,
  recording, readiness, limits and unsupported providers/accounting.
  **Depends:** NV-03–04. **Accept:** reach an internal fixture service, revoke/expire access,
  and reject other destinations; agents can discover capabilities without guessing tools.

**Exit:** one pinned local target can be deployed/reset, researched through HTTP/browser
and confined PoC tools, and stopped within durable limits. Containment remains enforced
for both human and agent callers; API/GUI/MCP share the same service boundary.

## P1 — independently verified, repeatable results

- [ ] **NV-06 — Strengthen independent validation.** Extend existing validators with
  class-specific effects and control experiments. Link request/action → observed effect →
  verdict with immutable evidence; distinguish confirmed, refuted, inconclusive and
  infrastructure failure. Keep hidden truth and operator-only exports outside agent access.
  **Depends:** P0 runtime. **Accept:** positive/negative/control fixtures reject persuasive
  unsupported claims; findings remain reviewable/reproducible after arena teardown.
- [ ] **NV-07 — Durable experiments and paired comparisons.** Extend ADR-0010's event-derived
  export with versioned Agent build, Challenge/Suite, Evaluation, Run and Trial records.
  Pin model/scaffold/tools/config, target/version, initial state/seed, budgets and validators;
  resume or terminalize interrupted trials. Repeated paired trials report outcomes, false
  claims, requests, latency, available cost, uncertainty and infrastructure failures.
  **Depends:** NV-02, NV-04, NV-06. **Accept:** compare builds A/B on matched conditions from
  the GUI/API and explain a change without conflating broken infrastructure with agent failure.
- [ ] **NV-08 — Small dependable challenge library.** Begin with one resettable authorization
  fixture, then cover sessions/business logic, browser behavior and service faults as used.
  Version synthetic accounts/seed data, private truth, validators and leakage labels.
  **Depends:** NV-02, NV-06; grow alongside NV-07. **Accept:** repeated trials catch a known
  agent regression; public known-vulnerability fixtures are labeled calibration, not held-out
  capability evidence. Broad challenge intake is not a prerequisite for the first useful run.
- [ ] **NV-09 — Bughunt integration and usefulness proof.** Joint versioned test/evidence
  manifest with BH-13: target/scenario, build/tools, seed, budgets, controls, observed outcomes,
  provenance and digests. Use synthetic identities, never live bounty credentials/captures.
  **Depends:** NV-02–06 plus the first NV-08 fixture for a vertical run; NV-07 for durable
  repeated comparisons. **Accept:** reproduce one bounty-agent workflow, retain independently
  validated evidence, reset, repeat with one agent change, and detect a seeded regression.
  Record setup effort/reuse and whether this improves the operator's actual workflow.
- [ ] **NV-10 — Recover research and experiment records.** Versioned consistent backup and
  restore of research DB/events, scenarios/target manifests, evidence/transactions, traces,
  experiment records and protected encryption keys/configuration. Separate redacted sharing
  from full recovery. Validate digests, schema and references before restoring.
  **Depends:** NV-07 record schema. **Accept:** restore onto a clean instance, decrypt/review
  an old result and rerun a pinned fixture; teardown/retention cannot destroy sole evidence.

**Exit:** repeatable independently validated research and a durable paired agent comparison
work through the normal console/API. Use NV-09's evidence to decide expansion; preserve a
focused maintenance scope if broader features do not improve actual research.

## P2 — research iteration driven by target needs

- [ ] **NV-11 — Affected-versus-fixed replay.** Link a finding/PoC to exact vulnerable and
  fixed versions and their configurations; compare effects and retain both evidence sets.
  Extend existing Git diff/patch artifacts with targeted variant hypotheses.
  **Depends:** NV-02, NV-06, NV-10. **Accept:** reproduce a flaw and show its observed effect
  disappears on the fixed version under matching controls; unknown versions remain unknown.
- [ ] **NV-12 — Fuzzing and crash triage when selected research needs it.** Bounded harness,
  corpus/seed and build identity, existing crash oracle, minimization, deduplication and
  reproducible crash bundle. **Depends:** NV-03–04, NV-06, NV-11.
  **Accept:** a minimized input reproduces a distinct fault with configuration/evidence.
- [ ] **NV-13 — Binary/appliance/local VM intake when a concrete target requires it.**
  Immutable image/installer identity, snapshots, reset, containment and before/after manifests;
  establish a live local hypervisor lifecycle before claiming provider support.
  **Depends:** proven Docker path and NV-10. **Accept:** reproduce and reset the selected
  non-source target; no source-diff approximation for binary evidence.
- [ ] **NV-14 — Research campaigns and disclosure bundles.** Group local research sessions,
  deduplicate findings by affected identity, track version/fix/disclosure state and generate
  sanitized reproducible output. **Depends:** NV-10–11.
  **Accept:** trace one finding across versions and produce a reviewable disclosure bundle;
  do not duplicate Bughunt's live bounty scope/scouting/credential management.
- [ ] **NV-15 — Held-out proof and optional active episodes.** Build private challenges from
  confirmed research findings with truth withheld; repeated trials, leakage policy, build
  identity and uncertainty. Add staged releases or LLM-app targets when used by the agent
  under evaluation. **Depends:** NV-07–11 and suitable confirmed research material.
  **Accept:** publishable discovery and comparison artifacts meet ROADMAP section 8's
  distinct acceptance criteria; publication itself remains a separate operator action.

## Deferred breadth

Cloud provider parity, hosted multi-tenancy/SSO/billing, broad public leaderboards,
multi-agent red-vs-blue, defender scoring and VNC remain deferred. Local VM work is NV-13
and requires a selected research target; cloud apply is not its prerequisite. No GPU-heavy
workloads or local model training are required for the personal Docker path.

## Implemented foundations — preserve, then reverify

- [x] Dynamic nodes/segments and Docker provider; immutable Git/OCI/source-bundle intake.
- [x] MCP gateway, stance/arena bindings, audit trace and binding pause.
- [x] SUT setup, Git changes/patch evidence, bounded file transfer and browser primitives.
- [x] HTTP request/transaction storage/replay, MCP tools, console and finding digest attachment.
- [x] Monitor, deterministic validators, scores, event-derived exports and reference harness.
- [x] Console engagements/workspace/activity, SSE and retained post-teardown evidence views.

These are implementation status, not a claim of verification beyond the recorded gates. NV-01
re-established the supported-runtime gate; NV-02 established the live deployment/reset gate.

## Mapping from ROADMAP milestones

| Existing milestone | Current checklist |
|---|---|
| S1–S3 / C1–C4 | Foundations; harden/reverify in NV-01–02 and NV-06 |
| S4 / R1 HTTP | Implemented; deployment acceptance in NV-01–02 |
| R2 confined execution | NV-03 |
| R3 pivoting/budgets/stop | NV-04–05 |
| E1–E5 experiments/drivers/library/comparison | NV-07–09; active episodes later in NV-15 |
| D1 patch/variant; D2 fuzzing; D3 VM/binary; D4 campaigns | NV-11; NV-12; NV-13; NV-14 |
| P1 proof; P2 optional LLM targets | NV-15 |

Detailed legacy design remains in ROADMAP.md; its section numbering is not execution order.
