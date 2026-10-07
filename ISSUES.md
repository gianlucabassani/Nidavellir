# Nidavellir — open risk register

Updated 2026-10-07 after the independent audit. MODEL-R1 and NV07-R1
remain closed for calibration machinery only. RESEARCH-R1/R4 are closed for the new
structured gate after Phase 2 verification; historical chronology is not repaired;
mail probe validity, incomplete coverage and historical evidence gaps remain open.

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
Benchmark and Cyber Range paths. The default cutover was approved on 2026-10-07
and the fallback drill passed; the session-expiry, CSRF-denial and reconnect
browser journeys and formal accessibility/usability review remain open. Record
these and the remaining parity/live-service checks in `docs/verification/`.

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

**Accepted retractions (2026-10-07):** the Paperless verdict is **no confirmed
vulnerability under the tested conditions**, not "exhausted for fix-derived shapes".
The count is **12 retained hypotheses plus 9 asserted without per-probe evidence**,
not 21 evidence-backed refutations. The six H rows recur in the mail artifact;
they must not be counted twice. Historical evidence files are unchanged.
Accepted audit: `docs/verification/research-audit-2026-10-07.json`.

### RESEARCH-R7 · Mail denials do not isolate object protection · high · open

M2/M4/M5 run without the member's mail mutation permissions and can be denied
before the intended object check. M5 sends only one admin-owned mail ID, not a
mixed batch; its control asserts listing status, not target-row survival. H2/H3
and M2/M3/M5 classifiers can refute despite a failed recorded control. M1/M4
observational controls are no longer mislabeled `held: false`, but that schema
correction does not validate their inference. H5 lacks a mutation control.

**Closes when (Phase 3):** grant the required global permissions while withholding
foreign-object permission; demonstrate allowed member mutations; use a genuinely
mixed M5 batch and check each target row survives. Re-run into new evidence
artifacts with request/response/control observations; preserve old artifacts.

### RESEARCH-R8 · Coverage and absence inference are incomplete · high · open

The original 17/26/5/8/353 match counts reproduce, but only 50/353 queryset sites
were classified. The omitted 303 include 44 `views.py` and all 33 mail matches.
Rules do not encode all nine fix rows: serializer/viewset paths, privilege flag
parsing, template context and check-before-mutation semantics lack complete
coverage. The original method-name union and irrelevant/discarded `has_perm`
false positives are corrected in Phase 1 (RESEARCH-R6); syntactic guard presence
still does not prove dataflow dominance, class enforcement or caller safety.

**Closes when:** each fix shape is tested against affected/fixed code and all
residuals have retained evidence. A manual-review/heuristic-limit site remains
unresolved, not zero actionable. New scans must not resurrect the exhaustion claim.

### RESEARCH-R9 · Historical counts, determinism and efficiency lack retained proof · medium · open

Nine initial endpoint refutations lack per-probe evidence. One retained fixture
build has seven matching controls and a recomputable matrix digest; it cannot
prove the asserted two-build determinism. Historical 977/981, 991/995 and
1002/1006 release totals have no cited raw October gate output. They are unverified,
not established fabrications. Six collect/derive calls and 416 output lines are
supported; the manual ~600-line/~10-call baseline is hardcoded and the ~4× saving
is unsubstantiated (600/416 is ~1.44 before unmeasured follow-up reads).

**Closes when:** historical execution logs are located, or claims remain explicitly
unverified. New reproducibility/verification results are dated separately and do
not retroactively certify old runs.

### RESEARCH-R10 · Code-intel audit and budget claims exceed implementation · medium · open

Successful REST calls append one audit event; failures return before auditing.
MCP wrappers trace calls but neither check nor charge a research budget. Digest
binding and operator-only surfaces are present. The directory fallback is fixed
in Phase 1, but checkout provisioning/ref immutability remains operator-owned.

**Closes when:** failed admitted calls have metadata-only audit events, and the
budget contract is either implemented with a defined authoring scope or explicitly
withdrawn. No audit/budget implementation is included in Phase 1.

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

### RESEARCH-R1 / RESEARCH-R4 · Registration/execution correspondence · Phase 2 corrected 2026-10-07

The old ancestor/two-substring check admitted unrelated registration text and did
not bind target, IDs, requests/controls or executable identity. Registered M6
was trash listing/deletion; executed M6 was account detail, with the same label.
This historical gap remains accepted; no future gate repairs its chronology.

The new gate reads a committed structured manifest and compares target pins,
ordered IDs, canonical executable request/control/setup/classifier definitions,
and probe/fixture/gate/Git-runner hashes. Marker substrings are advisory only.
A single captured snapshot binds both source and loaded-code checks; all five
probe functions, including the wrapper, must match. Checked fixture bytes are
compiled after admission. Result receipts retain both identities and reject
missing/duplicate/extra/reordered recorded IDs. Setup failures are recorded rows,
not proof that every probe executed. M6 same-ID substitution, source/fixture
races and stale-code/wrapper regressions are covered by scratch tests.

**Boundary:** new correspondence machinery only; Phase 3 control validity,
standalone fixture isolation, broader coverage and audit/budget contracts remain
open. No Paperless rerun or empirical registration occurred in Phase 2.
Contract: `docs/research/registration-contract.md`. Verification:
`docs/verification/research-phase2-2026-10-07.json`.

### RESEARCH-R5 · Code-intel helpers, egress and silent cuts · Phase 1 corrected 2026-10-07

Previously Git inherited configured helpers and could lazy-fetch missing blobs;
`layer_diff` silently cut at 65536 characters and claimed complete counts. Phase 1
neutralizes external diff/textconv, hooks, fsmonitor and Git environment overrides;
disables system/global config, lazy fetching and every transport; bounds both
subprocess pipes and the JSON envelope. Input cuts report incomplete counts; field,
row and file cuts are explicit. An unset RESEARCH_REPO_DIR is refused. Scratch
regressions exercise configured diff/textconv and promisor helpers, multibyte caps,
long evidence, site caps and source caps. Verification artifact:
`docs/verification/research-phase1-2026-10-07.json`.

### RESEARCH-R6 · Rule false coverage and undifferentiated review · Phase 1 corrected 2026-10-07

Method scopes resolve through qualified owner/definition spans. Global permission
arguments must match the owner-check permission and occur in recognized denying
conditions; unused calls do not guard actions. Manager queries include all/get/
exclude and other methods. Every manual-review site carries a classification:
unparsed source, dynamic permission, framework query, custom/inherited policy,
or owner-check dataflow unverified. Accumulators distinguish initializer,
AND composition, deny reset and overwrite. Class markers remain unresolved
framework references. This corrects the reproduced mechanisms, not RESEARCH-R8's
completeness gap. Verification artifact: `research-phase1-2026-10-07.json`.

### RESEARCH-R2 · Non-asserting controls read as `held: false` · closed 2026-10-06

M1/M4 observational controls carried `"held": false`. Closed by the
`assertive` flag (`held` only when a value is asserted) and the
re-emitted `paperless-mail-hunt-2026-10-06-corrected.json`
(`controls_schema: assertive-v1`): all 11 control blocks changed schema
(9 gained the flag, 2 dropped `held`), 12 verdicts
identical, zero `held: false`. Historical M1/M4 verdict labels remain unchanged; probe validity is open in RESEARCH-R7. (Correction: this entry
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
