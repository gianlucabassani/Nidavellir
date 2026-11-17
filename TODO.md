# Nidavellir — ordered delivery checklist

Updated 2026-10-18 after UI-R3 acceptance and independent review.
This is the canonical work queue. [ROADMAP.md](ROADMAP.md) retains product scope,
design detail and legacy milestone mapping. Unchecked means unfinished.
Verification is reproducible through the `make verify-*-live` gates, `scripts/verify-*-live.py` and `compose/acceptance/`.

## Scope and success

Build a professional local research and agent-testing platform: reproduce a target,
give a human/BYO agent a contained research position, independently validate the result,
reset and compare a changed agent or target. Docker-local is the first supported path.
Discovery and evaluation both remain in scope; broader research features follow a
demonstrated target need. Any MCP-capable BYO client can use the scoped gateway; Bughunt
is one example, not a dependency, and live bounty campaigns stay outside this platform.

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
- [x] **NV-04 — Durable budgets and stop controls.** Persist and atomically account action
  and time budgets across gateway reconnects, concurrent calls and worker restart. Token/cost
  accounting uses observable driver data; unsupported enforcement is explicit and budget-
  constrained jobs refuse to start when required accounting is unavailable. Reserve before
  execution and reconcile outcomes. Extend existing binding pause to arena/system stop,
  rejecting new work and cancelling/draining helpers with final traces.
  **Depends:** NV-03. **Accept:** reconnect cannot reset budgets; racing requests cannot
  exceed reservations; stop terminates helpers and does not lose evidence or final state.
- [x] **NV-05 — Scoped research access and runtime capabilities.** Add foothold-scoped
  forwards only for the selected research workflow: explicit destination, expiry, cleanup,
  binding and audit. Publish a bounded REST/GUI/MCP manifest for supported operations,
  recording, readiness, limits and unsupported providers/accounting.
  **Depends:** NV-03–04. **Accept:** reach an internal fixture service, revoke/expire access,
  and reject other destinations; agents can discover capabilities without guessing tools.

**Exit:** one pinned local target can be deployed/reset, researched through HTTP/browser
and confined PoC tools, and stopped within durable limits. Containment remains enforced
for both human and agent callers; API/GUI/MCP share the same service boundary.

## P1 — independently verified, repeatable results

- [x] **NV-06 — Strengthen independent validation.** Extend existing validators with
  class-specific effects and control experiments. Link request/action → observed effect →
  verdict with immutable evidence; distinguish confirmed, refuted, inconclusive and
  infrastructure failure. Keep hidden truth and operator-only exports outside agent access.
  **Depends:** P0 runtime. **Accept:** positive/negative/control fixtures reject persuasive
  unsupported claims; findings remain reviewable/reproducible after arena teardown.
- [x] **NV-07 — Durable experiments and paired comparisons.** Extend ADR-0010's event-derived
  export with versioned Agent build, Challenge/Suite, Evaluation, Run and Trial records.
  Pin model/scaffold/tools/config, target/version, initial state/seed, budgets and validators;
  resume or terminalize interrupted trials. Repeated paired trials report outcomes, false
  claims, requests, latency, available cost, uncertainty and infrastructure failures.
  **Depends:** NV-02, NV-04, NV-06.   **Accept:** compare builds A/B on matched conditions from
  the GUI/API and explain a change without conflating broken infrastructure with agent failure.
  *Closed 2026-10-06: model-driven paired suite complete (baseline full surface
  vs candidate without report_finding, 3 seeds, verified difference −1, zero
  infra-failed pairs, cost explicitly unavailable); NV07-R1 closed.*
- [x] **NV-08 — Small dependable challenge library.** Begin with one resettable authorization
  fixture, then cover sessions/business logic, browser behavior and service faults as used.
  Version synthetic accounts/seed data, private truth, validators and leakage labels.
  **Depends:** NV-02, NV-06; grow alongside NV-07. **Accept:** repeated trials catch a known
  agent regression; public known-vulnerability fixtures are labeled calibration, not held-out
  capability evidence. Broad challenge intake is not a prerequisite for the first useful run.
- [x] **NV-09 — BYO-agent workflow proof (harness-agnostic).** Any operator-selected
  MCP client drives active testing through the scoped gateway — opencode, Claude Code,
  Codex or Bughunt as one example; no client is a dependency. Nidavellir owns the pinned
  target, budgets, controls, observation digests and independent validation. Versioned
  test/evidence manifest: target/scenario, build/tools, seed, budgets, controls, observed
  outcomes, provenance and digests. Use synthetic identities and calibration fixtures;
  live campaign credentials/captures stay out of scope.
  **Depends:** NV-02–06 plus the first NV-08 fixture for a vertical run; NV-07 for durable
  repeated comparisons. **Accept:** reproduce one agent workflow (the synthetic-SPA
  vertical slice — two accounts, one owned object, one cross-account comparison, one
  restart; broad autonomous crawling excluded), retain independently validated evidence,
  reset, repeat with one agent change, and detect a seeded regression. Record setup
  effort/reuse and whether this improves the operator's actual workflow. First direct
  runs (opencode + opencode-go/deepseek-v4.1-flash on the NV-06 and NV-09 fixtures) are
  reproducible with `make verify-nv09-live`. A paired run against the same SPA
  fixture (baseline vs the same harness with the HTTP tool removed) detected the
  regression: verified difference -1.0, two matched pairs, zero infrastructure-failed
  pairs (`scripts/verify-byo-agent-pair.py`). Closed after
  operator review: setup reuses the pinned fixture and gate, and the paired result was
  judged worth the operator's actual workflow.
- [x] **NV-10 — Recover research and experiment records.** Versioned consistent backup and
  restore of research DB/events, scenarios/target manifests, evidence/transactions, traces,
  experiment records and protected encryption keys/configuration. Separate redacted sharing
  from full recovery. Validate digests, schema and references before restoring.
  **Depends:** NV-07 record schema. **Accept:** restore onto a clean instance, decrypt/review
  an old result and rerun a pinned fixture; teardown/retention cannot destroy sole evidence.

**Exit:** repeatable independently validated research and a durable paired agent comparison
work through the normal console/API. Use NV-09's evidence to decide expansion; preserve a
focused maintenance scope if broader features do not improve actual research.

## Audit remediation — phased before further research conclusions

- [x] **Phase 1 — Code-intel correctness.** Bound Git output, disable configured
  helpers and transports, report all cuts/incomplete counts, use owner-scoped AST
  definitions and permission arguments, broaden manager queries, classify review
  reasons. Acceptance: scratch regressions plus pinned release gate.
  Does not establish exhaustion.
- [x] **Phase 2 — Registration/execution correspondence (RESEARCH-R1/R4).** Committed
  structured registration binds target, ordered IDs, executable request/control
  definitions and probe/fixture/gate hashes; refusals precede fixture import.
  Receipts retain both identities; M6 substitution and loaded-code/race regressions
  pass. Contract: `scripts/research_registration.py`.
  No historical chronology repair
  or mail-control validity implied.
- [x] **Phase 3 — Isolation-valid probing (RESEARCH-R7).** Grant global permissions
  while withholding object permission; prove allowed mutations with requester-owned
  controls; test genuinely mixed batches with row-survival assertions; rerun into
  new artifacts. Depends on Phase 2. (First application: Paperless mail round.)
  *Closed 2026-10-12: final registration `b059439`; all assertive controls held,
  eleven request-scoped refutations and one globally authorized group-management
  result. Owned controls, concrete requests and mixed-row survival are retained.*
- [x] **Research-quality follow-up (RESEARCH-R8–R10).** Retain complete paged current
  inventories and nine affected/fixed source shapes; keep unresolved semantics
  explicit; reconcile unsupported historical claims; audit admitted query failures
  and withdraw the unsupported authoring-budget promise.

Accepted record: **no confirmed vulnerability under the tested conditions**;
**12 retained hypotheses plus 9 asserted without per-probe evidence**. Historical
artifacts stay unchanged. Historical proof gaps are explicitly unverified; new
evidence is dated separately. Source candidates remain unresolved until semantic
review. UI-R2 and UI-R3 acceptance is recorded below; source browsing remains
a separate unfinished slice.

## Review Phase 0 — do-first safety and correctness (FR-01–FR-09)

Registered 2026-11-16 from an independent security and correctness review.
Parallel-safe packages, one commit each. A box is ticked only when each
Accept line is met by a test that ran; live gates are operator actions and are recorded
as pending with the exact command.

- [x] **FR-04 — Close the agent-key read and deploy holes (B4, B5, U5).** Operator-only
  `GET /deployments`, `GET /events`, `POST /deploy` and `POST /arenas/custom`; `GET /status/{id}`,
  per-arena events and the agent-session announcement require the caller's binding to that
  arena; an event-type allowlist (`event_visibility.py`) replaces the denylist; agent
  self-deploy auto-binding is removed. **Accept:** an unbound agent key gets 403 on each
  route; a bound agent sees only allowlisted event types for its own arena; gateway tests
  still pass. *Met 2026-11-16: `tests/test_fr04_agent_read_scope.py` (19 of its 28 tests fail
  on the unfixed tree) and the full hermetic suite. Live scripts `verify-nv14-live.py` and
  `verify-ui-r4-live.py` were adapted to the refusal; their rerun is pending the operator.*
- [x] **FR-03 — Fail closed on insecure configuration (B14, B15, B23).** Outside MOCK_MODE
  the orchestrator, console and gateway refuse the dev key, a missing encryption key, a
  default console secret/password, or an empty/admin-role gateway key; Redis is
  password-protected and unpublished; the provider default is docker-local.
  **Accept:** a parametrized test per refused condition; `make dev` starts with no `.env`. *Met 2026-11-16 by `tests/test_fr03_fail_closed.py`; the live `make dev` start is pending the operator.*
- [x] **FR-07 — Real health and readiness (B12).** `/health` liveness; unauthenticated
  `/ready` 200 only if DB, Redis and (docker-local, non-mock) a fresh worker heartbeat
  answer; Compose health checks use `/ready`. **Accept:** stopping Redis or PostgreSQL
  turns `/ready` 503 within one interval. *Host-met 2026-11-16 by `tests/test_fr07_readiness.py` (failing probes give 503); stopping the real containers is pending the operator live gate.*
- [x] **FR-08 — Timestamps and indexes (B9).** `ix_events_lab_type_id`, `ix_events_type_id`;
  tz-aware UTC writes in `database.py`. **Accept:** PostgreSQL `EXPLAIN` uses the indexes;
  a DST-boundary unit test passes. *DST tests and SQLite planner check met 2026-11-16 (`tests/test_fr08_time_indexes.py`); the PostgreSQL `EXPLAIN` is pending the operator.*
- [x] **FR-05 — Bound arena target containers (B8).** Default mem/pids/cpu limits and
  `no-new-privileges` per node, overridable within a server ceiling, opt-out recorded in
  the manifest. **Accept:** a kwargs test; fixtures' live gates and a fork-bomb live gate. *Kwargs test met 2026-11-16 (`tests/test_fr05_node_limits.py`); fixture and fork-bomb live gates pending the operator.*
- [x] **FR-06 — Pin and narrow the capture sidecar (B7).** Digest pin, capability/ro-root/
  limits narrowing. **Accept:** MITM tests and one live capture pass. *MITM + new sidecar tests met 2026-11-16 (`tests/test_fr06_capture_sidecar.py`); the live capture is pending the operator.*
- [x] **FR-02 — Serve the console with gunicorn (B16).** gunicorn, session cookie flags,
  security headers + CSP, login throttling. **Accept:** release smoke on gunicorn, no CSP
  violation in a browser, sixth rapid failed login refused. *Throttle/header/cookie tests met 2026-11-16 (`tests/test_fr02_console_server.py`); gunicorn release smoke and the browser CSP check are pending the operator.*
- [x] **FR-01 — Run migrations at deploy and stop masking drift (B10, U4).** **Accept:**
  0009 → deploy path → 0010 column present; a revision mismatch exits non-zero. *Met on SQLite 2026-11-16 (`tests/test_fr01_migrations.py`; U4 proven); PostgreSQL copy-of-production migration and the deploy are pending the operator.*
- [ ] **FR-09 — Finish NV-14.** Independent review + closure report; live rerun is the
  operator's. **Accept:** as `NV-14`. *2026-11-16: fix review done and accepted; live rerun (`scripts/verify-nv14-live.py`) and release gate pending.*

## Next — research usability

- [x] **UI-R2 — Controls and evidence review in the console.** Extend the existing
  console and artifact routes to show actor requests, prerequisite controls,
  observed effects, verdicts and linked evidence together. Preserve operator-only
  source authoring and existing execution budgets. **Depends:** Phase 3.
  **Accept:** review a real two-account case from the console; failed positive
  controls cannot appear as refutations; evidence remains available after teardown.
  *Closed 2026-10-16: real Docker-local two-account disclosure/denial and failed-control
  reviews passed in the console before/after teardown; missing action stayed unresolved,
  operator judgments survived refresh/reload, budgets were unchanged by review and all
  arena resources were reclaimed. Independent review findings were fixed. Pinned release:
  1,123 SQLite passes / four skips / six deselections, 1,127 PostgreSQL passes / six
  deselections. Reproduce with `scripts/verify-ui-r2-live.py`.*
- [x] **UI-R3 — Request comparison in the console.** Extend existing replay with named
  groups, duplication, account/object edits, response comparison and saved notes, using
  existing protected credential handling and execution budgets. **Depends:** UI-R2.
  **Accept:** duplicate an owned request, change object/account, compare results and save
  evidence without exporting credentials.
  *Closed 2026-10-18: approved bounded design; real Docker-local browser and MCP
  comparison passed, including object/account edits, immutable named pairs and notes,
  finding references, stopped replay refusal and post-teardown evidence. Reads left
  budgets unchanged; browser replay payloads contained no account tokens. All arena
  resources and the isolated stack were reclaimed. Independent review passed after
  fixes. Pinned release: 1,137 SQLite passes / four skips / six deselections, 1,141
  PostgreSQL passes / six deselections. Reproduce with `scripts/verify-ui-r3-live.py`.*
- [x] **UI-R4 — Source candidate review in the console.** Immutable refs, complete counts,
  paged residuals, classification reasons and affected/fixed patch links. **Depends:** UI-R2;
  remains after UI-R3 in delivery order. **Accept:** all retained sites are reachable,
  incomplete scans and unresolved semantics remain visible, review state survives reopening.
  *Closed 2026-11-10: approved design (D1–D7); live acceptance on an isolated Compose
  stack against the pinned Paperless checkout (`6f7ed1d4`). Two sessions matching the
  two 2026-10-12 capture scopes reproduced all nine counts exactly (4,368) with the same
  file-and-line sets; paging through REST, console and browser reached every site;
  incomplete scans stayed visible; review states survived restart, a removed checkout
  and an NV-10 restore; one altered byte failed closed; agent keys got 403. Independent
  reviews of slices 1–4 and slice 5 left no open important finding.
  Pinned release: 1,282 SQLite passes, 1,286 PostgreSQL passes. Statuses remain
  syntactic candidates, not findings. Reproduce with `scripts/verify-ui-r4-live.py`.*

## P2 — research iteration driven by target needs

- [x] **NV-11 — Affected-versus-fixed replay.** Link a finding/PoC to exact vulnerable and
  fixed versions and their configurations; compare effects and retain both evidence sets.
  Git-diff variant hypotheses move to the discovery-layer spec (operator sequencing,
  2026-10-05).
  **Depends:** NV-02, NV-06, NV-10. **Accept:** reproduce a flaw and show its observed effect
  disappears on the fixed version under matching controls; unknown versions remain unknown.
  Implemented: `variant_of` on both finding write paths and the MCP tool; the operator-only
  `GET /findings/{finding_id}` group with a whitelisted target identity and evidence-derived
  outcome. Live: CVE-2026-26012 confirmed on Vaultwarden 1.35.2 and refuted on 1.37.3, linked
  into one `disappeared_under_controls` group
  (`make verify-vaultwarden-live`); tests in
  `tests/test_finding_variants.py` and `tests/test_http_access_control.py`.
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
  live bounty scope/scouting/credential management stay outside this platform.
  In progress 2026-11-10 under an approved design (D0–D8). Slices 1 (campaigns,
  deduplicated finding groups, disclosure state), 2 (allowlisted, content-addressed
  bundle) and 3 (console views) are implemented, and slice 4's live acceptance on the
  Vaultwarden calibration pair passed (`scripts/verify-nv14-live.py`).
  **Not complete:** an independent review found two important defects — a downloaded
  bundle did not hash to its digest, and the evidence-support flag ignored whether a
  different version was run. Both are fixed with tests and the fixes were accepted on
  review. **Next action:** rerun `scripts/verify-nv14-live.py` on the fixed code, then
  flip this box.
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

## Separate track: operator UI — UI-R1 complete

The React console cutover and accepted UI-R1 parity work are complete. The default
console includes setup-output history, custom-topology authoring, provider selection
with verification labels, and archive/list actions. Real-service operations, session
expiry, CSRF denial, reconnect, keyboard, responsive, and accessibility checks are
recorded in the closure report and
the accessibility review.

Docker-local is the only live-verified provider; other providers require further
verification. Remaining research and evaluation work follows the NV checklist above.

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
