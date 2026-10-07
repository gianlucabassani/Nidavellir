# Nidavellir — open risk register

Updated 2026-09-29 after the Royal Command Research, Benchmark and Cyber Range
Docker-local browser journeys.

Known, currently-open risks and verification gaps. Each entry states what is
actually true today, why it matters, and the concrete evidence that would close
it. Completed work and its verification live in
[`docs/JOURNAL.md`](docs/JOURNAL.md); the ordered work queue is
[`TODO.md`](TODO.md). An entry is removed only when its closing evidence exists
in `docs/verification/`, not when the related task is merely planned.

Severity is the risk of drawing a wrong conclusion from the platform's output:
**high** — a stated result could be believed and be wrong;
**medium** — a result is correct but narrower than it reads;
**low** — operational friction with no effect on reported truth.

---

## Open — operator console migration

### UI-R1 · Console cutover needs parity and usability evidence · low

The running development SQLite file initially lacked
`model_connections.base_url` and `deployments.effective_provider`, and had no
Alembic revision. On 2026-09-28 it was backed up to
`/tmp/nv-ui-development-backup-2026-09-28.db`, reconciled with a clean schema
and stamped at revision `0009`. SQLite integrity passed, both existing
deployments remained, and the restarted Compose console returned 200 for
Research, Benchmark, Cyber Range, Targets and Settings data in Chromium.
One mock arena launched, its workspace and Browser/Transfer tabs loaded, and
it was destroyed through the React UI with its record retained. The UI now
labels this development simulation explicitly.

A separate disposable mock API database at the current schema served the new
Research, Benchmark, Cyber Range, Targets and Settings screens and accepted a
source-bundle upload/preview on 2026-09-28. That confirms those read/intake
contracts independently of the stale development database; it does not meet
the Docker-local closure criterion below.

On 2026-09-29 an isolated PostgreSQL/Redis/worker/WebUI Compose stack ran a
real Docker-local fixture through the React Cyber Range path: scenario import,
launch, HTTP transaction and linked finding, replacement reset, retained
original finding, replacement destroy and scenario deletion. The live run
found and fixed a transaction-list shape mismatch that had crashed the HTTP
tab. Both arena IDs had no labelled containers or networks after teardown;
the isolated stack and volumes were removed.

The same date, a separate Research browser journey uploaded and pinned a local
source bundle, ran and finished setup, completed a confined PoC, recorded an
observation, destroyed the arena and reopened the finding on its archived
record. A second isolated NV-07 stack completed a three-pair scripted
calibration comparison through the React registry and comparison screens:
all six trials completed, with zero infrastructure failures. See
`docs/verification/ui-research-benchmark-live-2026-09-29.md`. An arena event
filtering gap and disposable-stack reaper timeout were fixed during this work.
All tested arena resources and both disposable stacks were removed.

On 2026-10-07 (Releases G–H) the console gained native Score/Challenges, run
attribution, service forwards, the agent connect recipe, All arenas (destroy,
remove, clear archive), All evaluations, capacity, Activity filters, a Forge
sign-in page and a stepped research intake. Remaining legacy-only surfaces:
setup command output, the custom topology builder and non-Docker-local
launches. Forwards, archive removal and destroy-from-list have browser and
unit coverage with mocked service calls only. The operator approved the console
after manual review on 2026-10-07 and it is now the default UI; the live fallback
drill passed both ways (`WEBUI_DEFAULT_CONSOLE=false` restores the legacy home,
`/?legacy=1` reaches it while the console is default).

**Why it matters:** successful read-only pages and a clean release gate do not
prove launch, arena operations, evidence retention or Docker-local task parity.

**Closes when:** route/action parity, browser denial and failure states, and
retained-record inspection are verified across the intended Research,
Benchmark and Cyber Range paths. Complete the manual accessibility/usability
and fallback gates before default cutover. Record the result in
`docs/verification/`.

---

## Open — evaluation evidence (NV-07)

### NV07-R1 · Only one deterministic driver has been exercised · medium

Paired evaluation is proven with `scripted-mcp/v1`, a fixed tool plan replayed
identically on every trial. No model-driven bring-your-own agent has ever run
through the evaluation path, so variance, retries, tool misuse, budget
exhaustion under real reasoning and partial-progress scoring are untested.
No operator model connection is configured for the durable evaluation path.
An authenticated local Claude CLI is not such a connection or a completed
model-driven trial; each subscription-backed live run requires separate
operator permission and none was used for NV-08.

**Why it matters:** the workbench's purpose is comparing real agent builds. A
deterministic script exercises the record and comparison machinery, not the
conditions those records are meant to describe.

**Closes when:** one model-driven build completes a suite through the same
endpoints, with its per-trial variance, token/cost attribution and any
budget/timeout terminations visible in the comparison. Tracked by ROADMAP E2.

---

## Open — carried from earlier gates

### NV06-R1 · Validated results rest on one calibration fixture · medium

The authorization and single-use-grant classes have independent validators,
versioned synthetic provenance and a live paired regression gate. Both remain
public calibration fixtures. No non-synthetic target has been independently
validated, so the closing criterion is not met.

**Why it matters:** calibration evidence must not read as capability evidence.
Exports and comparisons now label it explicitly; external validity remains open.

**Closes when:** NV-08 delivers challenges of known provenance and a result is
reproduced on one non-synthetic target.

### INFRA-R1 · Docker-local is the only live-verified provider · medium

`mock`, `docker-local`, `libvirt` and `openstack` drivers exist behind the
ADR-0003 abstraction. Only `docker-local` has passed live lifecycle, reset,
containment and teardown gates. Evaluation additionally refuses any other
provider outright.

**Why it matters:** driver code existing is not provider support, and the
repository should never imply otherwise.

**Closes when:** a live lifecycle gate passes on a second provider. Tracked by
NV-13 for local hypervisors; cloud providers remain deferred.

---

## Closed

### NV07-R2 · One challenge class, one fixture · closed 2026-09-26

The NV-08 isolated Docker gate paired authorization and single-use-grant
business logic with independent validators in one five-seed suite. It completed
20 trials, produced ten matched pairs, detected only the grant-step regression
(verified difference -1 for grants, 0 for authorization), counted zero
infrastructure-failed pairs and left zero labelled resources. The pooled
verified interval is `supported`; each constant per-class interval is
`degenerate`. Both classes are labelled calibration. Evidence:
`docs/verification/nv08-live-2026-09-26-bb79440f.json`.

### NV07-R5 · Evaluation recovery unexercised · closed 2026-09-26

Unit coverage (`tests/test_nv07_experiments.py`) drives
`recover_stale_evaluations`, `queued_evaluations_before` and `reap_labs` over
stale rows: unfinished trials become `infrastructure_failure/worker_interrupted`,
completed trials keep their results, a lost worker's late finish/claim is
rejected, recovery is idempotent and duplicate delivery is skipped.
`make verify-nv07-recovery-live` SIGKILLed the worker while a trial held an
arena, brought up a replacement worker and beat, confirmed the reaper left the
evaluation alone while its heartbeat was fresh, then — with 70 minutes of
silence simulated by backdating the heartbeat — the real reaper terminalized
the trial, the orphaned arena was reclaimed, a restarted worker did not reopen
the evaluation, and zero labelled resources remained. The kill landed on the
first trial, so the live run shows 0 matched / 3 infrastructure-failed pairs;
preservation of already-completed trials is proven by the unit test, not live.

The same change removed the "evaluation must fit one 61-minute task" limit:
trial claim/finish refresh the evaluation heartbeat, `enqueue_evaluation`
sizes the task limit from the suite, and a soft time limit terminalizes the
remaining trials as `infrastructure_failure/time_limit`.
Evidence: `nv07-recovery-live-2026-09-26.json`,
`nv07-hardening-gates-2026-09-26.json`.

### NV07-R4 · NV-02–06 live regressions not rerun · closed 2026-09-26

`make verify-nv02-live` through `verify-nv07-live` all passed at the heartbeat
change with zero labelled resources. Evidence: `nv02-regression-`, `nv03-live-`,
`nv04-live-`, `nv05-live-`, `nv06-live-` and `nv07-live-2026-09-26.json`.

### VERIF-R1 · Full host-Python suite stalled · closed 2026-09-26

The full non-integration suite completed on host Python 3.14.7 (913 passed,
4 skipped, 6 deselected, 13 s) twice with a 60 s faulthandler watchdog and no
stall. The 2026-09-07 root cause was not identified; host packages are
unpinned and differ from the lock. The pinned gate remains the contract (see
standing constraints).

### NV07-R3 · Degenerate bootstrap interval unlabeled in JSON · closed 2026-09-25

`experiments.compare` now emits `distinct_values` and `interval_status`
(`degenerate` / `insufficient_pairs` below five pairs / `supported` /
`no_pairs`) per metric in the `/evaluations/{id}` comparison, and the console
prints the status. The identical-pair `[1.0, 1.0]` case is labelled
`degenerate`. Evidence: `tests/test_nv07_experiments.py` in the pinned gate
recorded in `docs/verification/nv07-followups-gates-2026-09-25.json`.

---

## Standing constraints (not defects)

These are deliberate limits, recorded so they are not rediscovered as bugs.

- **No model token/cost hard caps for external BYO agents.** The orchestrator
  cannot reserve trusted pre-execution model usage, so `token_budget` and
  `cost_budget_usd` are refused at engagement creation, on research actions and
  in policy revisions. Action count and wall-clock deadline are the enforceable
  budgets; cost appears in exports only when a build announces it.
- **Evaluation records are operator-only by design.** Agent keys receive 403 on
  every evaluation endpoint and no evaluation record is exposed through MCP.
  Participant acknowledgements stay neutral — an agent is never told whether a
  finding was confirmed.
- **Only `make release-check` is authoritative.** Host-Python runs are useful
  signal but use unpinned packages; claims cite the pinned 3.11 SQLite and
  PostgreSQL gate.
- **Recovery is an offline operation.** Stop API, workers, beat and gateway before
  backup or restore; keep PostgreSQL available to the maintenance container.
  The encrypted bundle carries records, persistent files and the Fernet key,
  but OCI image bytes are not embedded. Replaying a pinned fixture on another
  Docker host requires that image by digest or its immutable build inputs.
- **Public known-vulnerability fixtures are calibration, never held-out
  capability evidence**, because participants may have trained on them.
