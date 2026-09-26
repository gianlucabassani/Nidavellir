# Nidavellir — open risk register

Updated 2026-09-26 after the NV-08 two-class live gate closed NV07-R2.

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
- **Public known-vulnerability fixtures are calibration, never held-out
  capability evidence**, because participants may have trained on them.
