# Nidavellir — open risk register

Updated 2026-09-25 after the NV-07 follow-ups (R3 closed, R5 narrowed).

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

**Why it matters:** the workbench's purpose is comparing real agent builds. A
deterministic script exercises the record and comparison machinery, not the
conditions those records are meant to describe.

**Closes when:** one model-driven build completes a suite through the same
endpoints, with its per-trial variance, token/cost attribution and any
budget/timeout terminations visible in the comparison. Tracked by ROADMAP E2.

### NV07-R2 · One challenge class, one fixture · medium

Every trial to date runs the NV-06 synthetic authorization fixture. The
challenge record pins a recipe digest and validator version generically, but
only `authorization_effect` has been paired, and that fixture is labeled
calibration, not held-out.

**Why it matters:** a comparison over a single known fixture cannot support a
capability claim, and a second class may expose assumptions baked into the
first (single-request actions, a target-local oracle, one point of truth).

**Closes when:** a second challenge class with an independent validator runs
paired trials in the same suite. Tracked by NV-08.

### NV07-R5 · Evaluation recovery not yet exercised against a real worker loss · low

`Database.recover_stale_evaluations` terminalizes worker-lost evaluations past
the hard task limit and `queued_evaluations_before` requeues stranded ones; the
reaper calls both. Since 2026-09-25 `tests/test_nv07_experiments.py` drives
both over stale `running`/`queued` rows and through `reap_labs`: unfinished
trials become `infrastructure_failure/worker_interrupted`, completed trials and
their results are preserved, the lost worker's late finish/claim is rejected,
recovery is idempotent, fresh/queued/complete evaluations are untouched, and a
duplicate delivery of a running evaluation is skipped. No live run has yet
killed the worker mid-trial.

Also note: recovery keys on `Evaluation.updated_at`, which only changes on
evaluation state transitions. That is safe only because `run_evaluation`'s hard
time limit (61 min) is below the 70-minute recovery threshold — an evaluation
must finish inside one task limit. Longer NV-08 suites need either a per-trial
heartbeat or a split task before they exceed it.

**Why it matters:** the unit tests prove the database contract; they do not
prove the reaper and a real Celery worker loss compose as intended.

**Closes when:** a live run kills the worker mid-trial and shows the reaper
terminalizing the trial as `infrastructure_failure` without corrupting the
comparison, recorded in `docs/verification/`.

### NV07-R4 · NV-02–06 live regressions not rerun after commit `03fdfc9` · low

The NV-07 change touches new code paths plus its own verifier, and the full
pinned release gate (Ruff, Bandit, 903 SQLite, 907 PostgreSQL) passed after it.
The earlier live acceptance gates were not rerun, unlike the NV-06 handoff,
which reran NV-02–05 after its final product change.

**Why it matters:** the shared worker, reaper and budget paths were extended.
Regression there would surface live, not in the unit gate.

**Closes when:** `make verify-nv02-live` … `verify-nv06-live` pass at this
commit or later with zero labeled resources, recorded in `docs/verification/`.

---

## Open — carried from earlier gates

### NV06-R1 · Validated results rest on one calibration fixture · medium

NV-06 proved independent authorization validation against a synthetic target
built for that purpose, with positive, negative, healthy-control, unsupported
and probe-failure cases. That is a calibration result. No held-out challenge
library, no real application, and no live cloud or VM target has been validated.

**Why it matters:** calibration evidence and capability evidence read alike in
an export row. The distinction must stay explicit wherever results are shown.

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

### VERIF-R1 · Only the pinned Python 3.11 Docker gate is authoritative · low

The 2026-09-07 review recorded the full suite stalling in `TestClient` on host
Python 3.14. Focused runs on the host venv work — `tests/test_nv07_experiments.py`
and `tests/test_webui.py` passed on 3.14 on 2026-09-25 — but a full host run is
still not trusted. `make release-check` runs the pinned 3.11 SQLite and
PostgreSQL suites in Docker and is the only gate a claim may cite.

**Why it matters:** a green focused run invites a "tests pass" claim the gate
would not support.

**Closes when:** the full suite completes on a current host Python, or the
stall is diagnosed and recorded as a wontfix with the pinned gate as the stated
contract.

---

## Closed

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
- **Public known-vulnerability fixtures are calibration, never held-out
  capability evidence**, because participants may have trained on them.
