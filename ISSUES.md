# Nidavellir — open risk register

Updated 2026-10-06: MODEL-R1 closed, NV07-R1 closed by the model-driven paired suite.
RESEARCH-R1 and RESEARCH-R2 opened by verification of the three Paperless research
rounds; RESEARCH-R3 opened deferred.

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

(no open evaluation-evidence items; NV07-R1 closed 2026-10-06, see below)

---

## Open — carried from earlier gates

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

## Open — research lane discipline (opened 2026-10-06)

R1 and R2 closed 2026-10-06 (see Closed); R3 stays deferred by its own trigger.

### RESEARCH-R4 · Pre-reg check binds ordering, not content · medium

**True today:** `--require-prereg` proves a *commit* predates the run, but
nothing binds that commit's *content* to the run — any old ancestor sha
(including one from an unrelated round) satisfies the check. Ordering is
mechanical; correspondence is still prose.

**Why it matters:** the failure mode R1 closed was silent reordering; the
remaining failure mode is a mismatched pre-registration passing the gate
unnoticed, which degrades the same fail-closed discipline one step
removed.

**Closes when:** the probe run records the pre-reg sha alongside the run's
parameters, and a check (human or mechanical) confirms the recorded
hypotheses match the pre-registration's. Minimal form: the attempt marker
carries both the pre-reg sha and the setup manifest digest, and the
journal result cites both.

### RESEARCH-R3 · Mail sink is embedded in the Paperless fixture · low

**True today:** GreenMail 2.1.14 (digest-pinned, SMTP 3025 / IMAP 3143 / HTTP
API, reset by recreating the mailbox user) is implemented inside
`cyber-range/fixtures/paperless/build_fixture.py`. It works, and its reset is part
of the determinism proof, but nothing is reusable — a second mail-bearing target
would copy it.

**Why it matters:** duplicated fixture plumbing is how fixture drift starts, and
the sink is the only general capability this lane added.

**Closes when:** a second target needs mail ingestion, at which point the sink is
extracted to a shared fixture component with the same digest pinning and reset
contract. **Deliberately deferred — no extraction before a second consumer.**

---

## Closed

### RESEARCH-R1 · Pre-registration ordering was not verifiable · closed 2026-10-06

Pre-registration and results landed in the same commit, so ordering was
prose, not history. Closed by the mechanical check:
`probe-paperless-variants.py` requires `--require-prereg` and refuses
before any stack work unless the sha is an ancestor of HEAD (proven by
failing twice + an in-process pass). Next round records both ids.

### RESEARCH-R2 · Non-asserting controls read as `held: false` · closed 2026-10-06

M1/M4 observational controls carried `"held": false`. Closed by the
`assertive` flag (`held` only when a value is asserted) and the
re-emitted `paperless-mail-hunt-2026-10-06-corrected.json`
(`controls_schema: assertive-v1`): all 11 control blocks changed schema
(9 gained the flag, 2 dropped `held`), 12 verdicts
identical, zero `held: false`. M1/M4 stay refuted. (Correction: this entry
first said only 2 blocks changed — the 9 asserting blocks changed too.)

### NV07-R1 · Only one deterministic driver has been exercised · closed 2026-10-06

A model-driven paired suite completed through the same endpoints: baseline
(`deepseek-v4.1-flash`, full five-tool surface) vs candidate (identical
except `report_finding` withheld via the `disabled_tools` build field) on
the pinned NV-06 calibration challenge, seeds 1–3, cap 12, deadline 600.
Six trials completed, three matched pairs, zero infrastructure-failed
pairs, zero residual resources. Baseline confirmed 1/1 on every seed
(filed with the observed digest after a 400→200 header-learning shape);
candidate observed the same 200 and ended its turn with nowhere to file.
Verified difference −1.0 (`degenerate` — constant, honestly labelled);
per-trial token attribution retained (4–7 calls, 5k–12k input tokens);
cost renders `not_reported` with "cost unavailable from this provider"
(token usage retained, cost explicitly unmeasured — the A4 resolution);
all terminations `model_end_turn` and visible. Guarded suite path
(single-attempt marker, freshness precondition, exact-parameter
assertion) now exists as `scripts/prepare-nv07-suite.py` /
`run-nv07-suite.py`. Evidence:
`docs/verification/nv07-suite-setup-2026-10-06-fd02d7f6.json` (+
`-attempt`), `nv07-suite-suite-2026-10-06-fd02d7f6.json`; green
`make release-check` (Ruff/Bandit clean, 991 SQLite / 995 PostgreSQL).

### MODEL-R1 · Model connections carry custom request headers · closed 2026-10-06

Model connections store operator-approved static `extra_headers`
(Fernet-encrypted at rest; masked views expose names + digest only),
validated at the API boundary (≤16, name shape, case-insensitive
deny/duplicate, no CR/LF; `Authorization` et al. refused so driver
credentials always win), forwarded through `/agent/model/verify` and every
durable `model-mcp/v1` provider call, pinned into agent builds as
`headers_digest` and checked at trial-match with drifted fields named.
Live: two single-shot calibration smokes ran the durable driver against
opencode-go (`deepseek-v4.1-flash`) with `User-Agent:
opencode-nidavellir/1.0` plus a static `x-opencode-session` — the
stored-credential verify returned `verified: True` and both trials
completed with real transcripts and provider-reported usage, zero residual
resources. Evidence:
`docs/verification/nv07-r1-setup-2026-10-06-{e7f3ba95,8063d12f}.json`,
`docs/verification/nv07-r1-smoke-2026-10-06-{e7f3ba95,8063d12f}.json`,
migration `0010_add_model_connection_headers`, and a green
`make release-check` (Ruff/Bandit clean, 977 SQLite / 981 PostgreSQL).

### NV06-R1 · Validated results rest on one calibration fixture · closed 2026-10-05

The authorization and single-use-grant classes had independent validators,
versioned synthetic provenance and a live paired regression gate, but both
remained public calibration fixtures with no non-synthetic result.

On 2026-10-05 the platform's generic `http_access_control` validator confirmed
CVE-2026-26012 on a pinned, non-synthetic Vaultwarden 1.35.2 arena (a regular
organization member retrieved a cipher in a collection it could not access,
while the owner control and the actor's allowed-control request behaved as
declared) and refuted the same request on the fixed 1.37.3 fixture with
`access_denied`. The gate runs on an isolated Docker-local stack, retains
observation/control evidence after teardown and leaves zero labelled
resources. The synthetic NV-08 fixtures remain calibration-only. Evidence:
`docs/verification/vaultwarden-live-2026-10-05-b4c1bd2c.json`,
`cyber-range/fixtures/vaultwarden/`, `scripts/verify-vaultwarden-live.py`.

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
