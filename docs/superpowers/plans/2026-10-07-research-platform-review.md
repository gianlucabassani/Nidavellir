# Research Platform Review and Prioritized Improvement Plan

**Status:** design and prioritization only; no implementation authorized by this document.
**Reviewed:** 2026-10-07, HEAD `9e9a961`. The existing uncommitted TODO edits generalize
Phase 3 to isolation-valid probing; they are preserved. No target probes, infrastructure,
external contact, or release gate ran in this review. Source inspection and one isolated
execution of the pure finding-group function inform the findings below.

**Goal:** make a research conclusion traceable to the exact hypothesis, execution,
healthy controls and retained effect before increasing discovery throughput.
**Architecture:** preserve worker-owned execution, Docker-local containment, append-only
events and operator-only truth. Introduce a small research-run interface over those
primitives; target adapters supply seeding, requests and observations. Static code intel
supplies candidates rather than security verdicts.
**Stack:** existing Python/FastAPI/Celery, PostgreSQL/SQLite and Docker-local.
**Basis:** ROADMAP sections 5/8/9, TODO audit remediation, ADR-0009/0010/0011/0014–0016.

## Constraints and review limits

Public known-vulnerability work remains calibration. No novel finding is banked by the
accepted Paperless record (`ISSUES.md:43`, `docs/JOURNAL.md:6`). No external campaigns,
credentials or third-party contact. UI is excluded. NV-12/13/14/15 remain conditional
(`TODO.md:146`). Runtime changes require the pinned `make release-check`, plus a scoped
live gate where acceptance depends on infrastructure; previous Phase 1 results are not
verification of future work (`docs/JOURNAL.md:33`). New target experiments must register
hypotheses before probing. Evidence exports must omit credentials and hidden truth.

This is a scoped design review, not an exhaustive containment audit. Docker settings are
source facts, not a fresh live containment proof. Header handling and evaluation arithmetic
were rechecked at their source/evidence seams; this pass did not replay the model suite.

## Findings ranked by cost of a wrong conclusion

### 1. Research execution is not bound to its registration — high

**Unsound:** `check_prereg` checks ancestry and independent substrings in added journal
lines; it does not compare target, IDs, requests, controls or script digest
(`scripts/probe-paperless-variants.py:49`, `:76`). `main` gates once, then executes its
hardcoded H/M probes (`:90`, `:245`). M6 executes account detail (`:315`), while the
accepted historical registration described trash operations (`ISSUES.md:54`). Merely
binding IDs would preserve this substitution. The IDs must refer to executable request
and control definitions, not prose descriptions with the same labels.

**State discrepancy:** the handoff says R1/R4 closed; source and registers say open
(`ISSUES.md:54`, `TODO.md:119`). No closure is justified here. Cost: evidence appears
pre-registered while describing a different experiment.

### 2. Mail verdicts can refute the wrong protection, or ignore failed controls — high

The member receives view permissions only (`cyber-range/fixtures/paperless/build_fixture.py:58`,
`:258`). M2/M4/M5 exercise mutations without proving the actor can perform allowed ones
(`scripts/probe-paperless-variants.py:258`, `:279`, `:293`). A global denial cannot isolate
object authorization. M5 sends one foreign ID (`:306`), labels a list-200 check as row
survival (`:309`), and classifies without inspecting that control (`:313`). M2 and M3
also ignore control health (`:268`, `:276`). `record` retains statuses but delegates the
verdict to each lambda (`:98`); it does not enforce healthy assertive controls centrally.

Contrast the existing read-disclosure validator: it rejects unhealthy owner/actor controls
before classifying effects (`cyber-range/services/scenario-orchestrator/validators.py:496`).
That is a useful contract to preserve, not a ready mutation/atomicity validator. Cost:
a misleading negative result steers research away from an untested weakness.

### 3. Variant grouping does not establish matched experiments — high

`_finding_group_outcome` compares validator ID/version, known identities and verdicts;
it reports recipe equality separately. It does not compare probe definitions, actors,
control predicates or non-version configuration
(`cyber-range/services/scenario-orchestrator/api.py:5152`). A confirmed reference plus a
refuted variant can become `disappeared_under_controls` (`:5178`). The finding write path
accepts a link to an existing finding; the link itself is not correspondence proof (`:5744`).

An isolated execution of this pure function with two known, different recipe digests and
matching validator labels returned:

```json
{"outcome":"disappeared_under_controls","validator_comparable":true,"identity_match":"different_recipe","counts":{"confirmed":1,"refuted":1,"inconclusive":0,"infrastructure_failure":0}}
```

Different recipes are necessary for version comparison; demanding equal recipe digests
would be wrong. The missing contract is declared, verified differences with matched
experiment semantics. Existing Vaultwarden live evidence remains a specific retained
comparison; this finding limits the generic group label, not that historical run's
observations (`TODO.md:134`). Cost: a linked result is mistaken for proof that a fix caused
the observed difference.

### 4. Paperless is a standalone harness, not a contained platform research run — high

The fixture directly creates/removes fixed-name host Docker resources
(`cyber-range/fixtures/paperless/build_fixture.py:195`). Its network creation does not
request `--internal` (`:204`); the web/sink publish loopback ports (`:221`, `:239`). Probes
call the fixture HTTP helper directly (`scripts/probe-paperless-variants.py:91`). These
paths do not enter platform PoC admission or scoped HTTP execution. This does not show
actual third-party traffic, but default Docker network creation does not establish the
platform's no-egress guarantee. Fixed names also make concurrent runs collide.

The fixture's public output removes tokens/share slug (`build_fixture.py:352`), which is
sound export hygiene for that path. The run still needs explicit execution-lane labeling,
ownership, containment and failure cleanup before autonomous reuse. Cost: broad automation
inherits an unproven containment/audit/reset contract.

### 5. Static rule results cannot support exhaustion; completeness remains expensive — high

Five searches exist, with Paperless helper names and permission markers
(`cyber-range/services/scenario-orchestrator/research_code.py:40`, `:473`, `:476`).
Owner-scoped definitions, literal permission arguments and classified uncertainty are
real Phase 1 improvements (`:352`, `:394`, `:564`). `composed` expressly means local
syntactic guard presence, not dominance/object identity (`:416`, `:556`). The queryset
rule treats owner-aware calls as unresolved dataflow (`:538`). Row cap 50 and grep byte
caps are explicit (`:490`, `:549`), but there is no continuation cursor; narrowing a path
cannot recover all sites inside one oversized file (`:334`).

All nine fix shapes still need affected/fixed calibration and residual review. F3's
privilege parsing and F4's template context are not encoded by the five patterns
(`docs/research/paperless-variant-table.md:12`, `:13`; `research_code.py:476`). The final
scan retains a lower bound of 459 queryset matches and 50 displayed sites
(`docs/verification/research-phase1-2026-10-07-scan.json`). Neither renamed statuses nor
zero confirms supply missing coverage. Cost: candidate extraction is sold as absence proof.

### 6. A held-out label is weaker than private provenance — high when used for comparison

Challenge creation rejects three named public synthetic seed schemas under `held-out`
(`cyber-range/services/scenario-orchestrator/api.py:6166`). It does not there establish
that another target's vulnerability/truth was never public. Comparison labels derive
from challenge labels (`cyber-range/services/scenario-orchestrator/experiments.py:352`).
A label is useful metadata, not a leakage attestation. Do not claim a new bypass of a
private-corpus system: this finding is that the required provenance system is missing.
Cost: calibration can acquire an unjustified capability label.

### 7. The crash oracle exists, but correlation is not input reproduction — medium/high

The earlier proposal says no crash oracle exists (`docs/research-proposal.md:55`);
that inventory is wrong. Docker observations feed state/log detectors
(`cyber-range/services/scenario-orchestrator/providers/docker_local.py:2600`,
`cyber-range/services/scenario-orchestrator/monitor.py:96`) and a periodic event writer
(`cyber-range/services/scenario-orchestrator/tasks.py:961`). Fingerprints derive from
kind, node and state/log text (`monitor.py:150`), not minimized input or symbolized stack.
`correlate_crash` confirms same-node signals within 120 seconds of an action
(`cyber-range/services/scenario-orchestrator/validators.py:282`). That is correlation,
not causal isolation, security impact or deterministic reproduction. Polling/log signals
can miss short-lived subprocess faults; source cannot settle actual loss rates here.
Cost: a unrelated fault is credited or a fuzzer's crash is lost.

### 8. Audit and efficiency claims remain narrower than the tooling narrative — medium

REST errors precede `_research_audit`; success gets one metadata event
(`cyber-range/services/scenario-orchestrator/api.py:6291`, `:6311`, `:6333`, `:6357`).
Search audit detail retains pattern but omits requested path scope (`:6361`). MCP wrappers
trace downstream success/failure but do not charge a research authoring budget
(`cyber-range/services/agent-gateway/gateway/tools.py:263`); stance rejection precedes
that wrapper's try/trace (`:37`). Authoring is not automatically an arena-budget action.
Its budget scope must be chosen rather than borrowed by implication.

Missing nine probe artifacts, historical raw gate totals, two-build proof and efficiency
baseline remain unverified (`ISSUES.md:94`). Fresh measurements cannot repair their
chronology. Source excerpts can contain literals: an output digest does not sanitize them
(`research_code.py:531`, `docs/research/research-code-tools-spec.md:78`).

## Claims that survive, with their limits

- Code intel uses allowlisted Git verbs, suppresses external helpers/transports and bounds
  both pipes with a timeout; result envelopes bind truncation and returned facts
  (`research_code.py:83`, `:185`). Phase 1 scratch/regression/release logs are retained
  in `docs/verification/research-phase1-2026-10-07.json`; no fresh release claim here.
- Paperless pins five images, seeds documents/mail and refuses seven unexpected matrix
  statuses (`build_fixture.py:35`, `:131`, `:306`). Its digest covers that status matrix
  (`:334`), not full state determinism; mail validity still depends on finding 2.
- Confined Python PoCs have a worker-owned endpoint and a networkless, resource-limited
  Docker runner (`api.py:2257`, `providers/docker_local.py:1009`). Preserve that runtime;
  it is not a general native fuzzer or VM sandbox (ADR-0014).
- MODEL-R1 bounds/denies custom headers and pins their digest (`model_headers.py:30`,
  `:46`, `:83`; `experiments.py:77`). The driver forwards approved extras while protecting
  credentials (`eval_model_driver.py:46`).
- The model suite retains three matched pairs and mean verified difference −1.0
  (`docs/verification/nv07-suite-suite-2026-10-06-fd02d7f6.json:126`, `:195`). Removing
  `report_finding` changes the reporting surface, not proven discovery capability;
  the current roadmap admits this (`ROADMAP.md:74`).

## Prioritized sequence

A = critical engineering/design (new interface/contract); B = deeper review of existing
code; C = execution-only work. These are proposed tasks, not newly scheduled NV items.

| Order | Type / deliverable | Dependencies | Acceptance and what it unblocks |
|---|---|---|---|
| 1 | A: registration/execution correspondence, Phase 2 | None beyond Phase 1 | Before any stack action, reject changed target, ID set, request/control definition, script bytes or registration chronology. Original M6 substitution fails even with unchanged ID. Valid run retains registration/execution digests. Unblocks honest reruns. |
| 2 | A+B: isolation-valid classifier and mail adapter, Phase 3 preparation | 1 | Global mutation grants verified separately from object denial; allowed actor-owned mutations work. Any failed required control produces infrastructure failure; missing/unexpected observations stay inconclusive. Mixed batches test both input orders and per-row before/after state. Unblocks meaningful mail execution. |
| 3 | B: fixture execution/ownership/containment review | 1; before automation | Choose platform arena or explicitly isolated operator harness. Verify no undeclared egress, no resource-name collisions, failure cleanup and secret-free export. Evidence states the chosen lane. Unblocks safe repeated research. |
| 4 | C: new mail run and two clean-build comparison | 2+3 | Pre-register, run fresh builds, retain each full request/control/row observation and teardown inventory. Separate stable semantic state from timestamps/IDs, retain both normalized digests. New dated results; no retroactive refutation/determinism claim. Unblocks target/layer decision. |
| 5 | A+B: comparison provenance contract | 1; before generic fix-effect claims | Bind root/variant to normalized probe, actor roles, controls, seed/config, validator implementation digest and declared version-only differences. Mismatched probe or permissions never yields disappearance. Mixed unresolved variants remain explicit. Unblocks stronger NV-11/NV-14 exports. |
| 6 | A+B: rule retrieval/calibration contract | Can review while 1–4 progress; no new target conclusions | Complete resumable retrieval within a pinned commit, deterministic no-duplicate cursor, stale-cursor refusal. Each F1–F9 has retained affected/fixed examples or an explicit unsupported shape. Test aliases/inheritance/overrides/early effects/dynamic args; retain residual review decisions. Unblocks useful candidate automation without absence claims. |
| 7 | A+B: admitted-call audit and authoring limits | 3 determines scope | Define operator authoring account vs arena charging vs explicitly unmetered authoring. Record one body-free terminal event per admitted success/error/cut with scope and input identity; separately handle authentication/stance failures. Concurrency/time limits survive MCP reconnect and REST use. Unblocks bounded automated collection. |
| 8 | A then C: one end-to-end research-run manifest | Contracts 1–7 | Join target/seed, registration, code-intel digests, executed actions, controls, classification, PoC/effects, retention and cleanup. Replay from a cold lab and independently recompute verdict. Measure actual effort/output bytes and follow-up reads against matched manual work. Unblocks justified automation/efficiency decisions. |
| 9 | C: one selected discovery round | 4+6+8 and design choices below | Fixed hypotheses and stop conditions, healthy controls, every row supported, no exhaustion inference. Stop/continue decisions based on unresolved mechanisms and setup cost, not advisory counts alone. A confirm enters independent proof; zero confirms remain zero. |

**Proposed file responsibilities:** registration parsing/binding in a new focused
`research_registration.py` beside orchestrator research modules; Paperless requests and
control extraction remain a target adapter, not core semantics. `scripts/probe-paperless-variants.py`
consumes the validated registration and produces executed-ID observations;
`build_fixture.py` owns fixture facts, not hypothesis verdicts. Existing `validators.py`
(or a focused sibling) owns shared control-health classification. `api.py` finding-group
projection consumes a comparison descriptor rather than inferring correspondence.
`research_code.py` remains candidate extraction; keep adapters/rule specifications out of
Git transport. Exact persisted schema/endpoint changes require the design decisions below
before a build plan; no campaign migration is approved by this review.

For every implementation task: first retain failing counterexamples, then the minimum
change, scoped regression evidence, independent review and the authoritative release
gate. Infrastructure acceptance additionally requires live isolation/reset/cleanup evidence.
Do not use a passing test total as a substitute for the task's specific acceptance.

## Automation and end-to-end research workflow

Automate deterministic collection, registration validation, bounded execution, control
health checks, state comparison, evidence hashing/retention, replay and cleanup. Candidate
ranking and hypothesis drafts can be machine-assisted, but drafts are not executions or
confirmed findings. Human/operator decisions stay at authorization scope, target selection,
security invariant, by-design interpretation, unresolved dataflow, novelty, impact and
release/disclosure approval. Do not automatically convert a search status into a verdict.

The desired loop is: choose target/layer → pin and isolate → verify seed/control matrix →
register fixed experiment → collect bounded candidates → execute declared probe/control
steps → classify observed effects → minimize/replay PoC → independently validate → retain
and export. Exploratory discoveries outside registration become a separately registered
follow-up, never a relabeled retrospective confirm. HTTP/body/row assertions belong to
target adapters; run provenance and control-health semantics belong to the shared module.

PoC improvement starts with portable recipes and observations on the existing confined
runner, not more execution power. A reproducibility bundle should name source/input,
runner image, target recipe, reset point, registration, action/observation digests and
expected predicates; unavailable artifact/target becomes an explicit replay failure.
Minimization must preserve the effect and healthy controls. Mutation replay requires fresh
state; uncertain interrupted jobs must not be blindly retried (ADR-0014).

## Do-not-build list and reopening triggers

| Defer | Trigger and prerequisite |
|---|---|
| General autonomous discovery/scanning agent | One complete selected research round demonstrates which collection/execution steps recur; contracts 1–8 and human scope approval first. The platform supplies evidence, not its own pentesting agent. |
| Fully generic static authorization engine | A second target demonstrates shared semantics and retained cross-target calibration beats simple adapters. No generic plugin framework for one helper vocabulary. |
| GreenMail extraction (R3) | A second mail consumer needs the same reset/transport interface. Until then review/fix the current adapter; no abstraction justified by duplication that has not occurred. |
| NV-12 native fuzzing, corpus campaigns and minimization | Selected parser/native target needs it. Decide runner images/toolchain and crash-input attribution first; cold-corpus calibration, minimized reproducible crash, controlled resource use and cleanup are acceptance. |
| NV-13 VM/binary/appliance intake | A selected target cannot be studied through Docker/source intake. Live local hypervisor lifecycle, immutable image, snapshot/reset and containment gates before support claims; no cloud expansion. |
| NV-14 full campaign/disclosure lifecycle | Multiple sessions/versions or a concrete confirmed finding require durable grouping/export. A manifest exporter may suffice before new campaign tables; no vendor contact automation. |
| NV-15 private corpus/active episodes | Suitable confirmed research material plus provenance/leakage policy, truth separation and repeated comparison. A `held-out` label alone never selects this work. |
| UI, cloud, tenancy, OAuth, purple-team, VNC, leaderboards | Separate operator-selected need/track per ROADMAP section 9; none improves today's research validity gap. |

## Design-confrontation agenda before building

1. **Registration as passive manifest vs executable request plan.** Compare a digest-pinned
   script plus structured definitions against a runner interpreting registered steps.
   Choose using the M6 same-ID substitution, dynamic fixture IDs, actor/control binding,
   included helper/fixture hashes and chronology tests. Recommended initial choice: a
   narrow executable descriptor with explicit target placeholders, plus script/adapter
   digests. A script digest alone permits a consistently registered but incorrectly
   described program; a manifest alone permits a program to ignore it.
2. **Operator fixture harness vs platform arena execution.** Compare setup flexibility
   and migration cost with stop/budget/audit/cleanup reuse. Require a cold-run trace,
   no-egress test, failure cleanup and resource ownership evidence. Prefer platform
   execution for repeated automated research; retain a labeled isolated harness only
   when a target setup need justifies it. No silent equivalence between the lanes.
3. **Per-target rules vs generic facts with target adapters.** Compare current Paperless
   rules, a small AST fact layer plus adapters, and a pinned external rule engine.
   Use F1–F9 affected/fixed examples plus a second target; measure missed shapes, false
   coverage, unresolved sites and follow-up cost. Preserve candidates as candidates.
   Do not select a generic engine solely because it returns fewer lines.
4. **Continue Paperless, change layer, or change target.** Corrected mail controls and
   residual coverage come first. Compare remaining untested mechanisms, validator fit,
   fixture cost and novelty risk. An unsupported shape selects a new layer experiment;
   a zero-confirm family does not establish exhaustion or require target abandonment.
   Historical advisory counts/saturation estimates do not establish discovery yield.
5. **NV-12 PoC reuse vs specialized bounded fuzz runner.** Python HTTP PoCs and native
   coverage-guided execution have different runtime/input/oracle needs. Use one selected
   harness to compare limits, instrumentation, subprocess fault capture, reproducible
   input linkage and cancellation. Reuse leases/artifacts, not an unproven runner contract.
6. **NV-14 exporter first vs durable campaign aggregate.** Compare a versioned manifest
   over existing event/PoC/variant records with campaign rows and a state machine.
   Evidence needed: actual repeated-session grouping, dedup ambiguity, version relation,
   artifact availability, sanitization and offline verification needs. No new aggregate
   until the exporter cannot express a concrete workflow.
7. **Private challenge provenance and truth isolation.** Compare policy attestation with
   machine-enforced access separation and build/export restrictions. Require a leakage
   threat model, origin history, participant-visible package inspection and clean rebuild.
   Public calibration exclusion must be general, not a list of three schema prefixes.

**Single highest-leverage next action:** design and implement Phase 2's registration-to-
execution correspondence contract, using the original M6 same-ID substitution as its
acceptance counterexample. It repairs the link between every planned hypothesis and its
observed result, enables valid Phase 3 reruns, and gives later automation, replay and
comparison a common identity. Faster probing before this contract only multiplies
untrustworthy evidence.
