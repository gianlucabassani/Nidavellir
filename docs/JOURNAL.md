# Development journal

Dated handoffs record changes and actual verification. TODO.md is the canonical ordered
work queue; ROADMAP.md retains design detail and historical milestone mapping.

## 2026-09-24 — Complete NV-06 independent authorization validation

**Outcome:** NV-06 is complete on Docker-local. Froze the five-case acceptance
matrix before changing validation/scoring and built a resettable, image-pinned
synthetic A/B authorization target first. The platform now links a participant's
recorded HTTP action to target-local effect read-back and a B-to-B healthy
control. An append-only `nidavellir/validation-verdict/v1` finding event cites
the pinned recipe/target, action, effect/control digests, validator version,
timestamp, four-way verdict and reason code. Observation files are arena-scoped,
content-addressed and integrity-checked; operators can review them after
teardown. REST/MCP agent acknowledgements remain neutral and agent events hide
private match/verdict and manual review. No migration was needed.

The marker validator now requires manifest-owned truth; passive crash credit
requires a linked same-node action within 120 seconds. Benchmark headline
success uses automatically confirmed points, while claim coverage and
digest-citing manual judgment remain separate. Discovery displays unlinked
faults without granting headline success. The console shows verdict/reason and
action/effect/control links. Code review caught and fixed a projection in which
manual confirmation displaced automatic proof; the final tests and gates ran
after that fix. ADR-0009 records the amended scoring contract.

**Files:** Authorization fixture and `docker-compose.nv06.yml`; scenario
schema, validator, evidence store, finding API and scorer; console findings,
score and evidence views; `scripts/verify-nv06-live.py`, focused tests,
`docs/API.md`, ADR-0009, acceptance/gate JSON, README, ROADMAP, TODO and this
journal. `docs/UI_REBUILD_PLAN.md` and prior journal entries are preserved.

**Verification:** Final `make release-check` passed on Python 3.11.14:
Ruff 0.6.9 clean, Bandit 1.9.4 with zero medium/high findings, 901 SQLite
tests passed (four PostgreSQL-only skips), 905 PostgreSQL tests passed, six
declared integration deselections on each backend, and clean Alembic plus
API/console/MCP readiness smoke. Final `make verify-nv06-live` passed:
positive A-to-B access `confirmed/unauthorized_read`; denied path
`refuted/access_denied`; B-to-B control `control_ok`; unsupported claim
`inconclusive/missing_action`; stopped target
`infrastructure_failure/probe_failed`. It also proved MCP neutral ack,
agent truth denial/redaction, reset observed-state equivalence, operator
console and transaction/effect/score review after teardown, and zero labeled
containers, images, networks and volumes across three arenas. The fixture image
was `sha256:cb5ba133686e30b5bab036d4431a5f6d04b27c1341a90f8f42be5b02f31f9b34`;
the final positive recipe was
`sha256:521be6a30198bb99adb95fe801e8e66b18ca8176c7134491550b844abf27f378`.

After the final product change, NV-02 reset/retained-evidence (five arenas),
NV-03 confined PoC (three), NV-04 durable budget/stop (two), and NV-05 scoped
forward (four) live regressions passed with zero final labeled resources.
The first NV-04 rerun hit its three-second expiry deadline during worker
shutdown, returning the expected 409 before the fixture could enqueue its
job; its failure cleanup left zero labeled resources. The verifier now stops
the worker before starting a 15-second deadline, and the next run passed.
Exact results and IDs are in `docs/verification/nv06-gates-2026-09-24.json`,
`nv06-live-2026-09-24.json`, `nv02-regression-2026-09-24.json`, and the
refreshed NV-03/04/05 live JSON. Final documentation/JSON validation and
`git diff --check` passed. Nothing was pushed.

**Unresolved risks / next step:** This is one calibration fixture and one
class-specific validator, not a held-out challenge library or a live cloud/VM
claim. Legacy validator evidence remains at its existing contract. Durable
paired Agent build/Challenge/Evaluation/Run/Trial records, repeated
comparisons and infrastructure-failure accounting are NV-07.

## 2026-09-23 — P1 vertical-result handoff after NV-05 checkpoint

**Outcome:** Committed the completed NV-05 implementation and passing evidence
locally as `7df304a`, without pushing. Replaced the completed NV-05 handoff in
`tmp-implementationPlan.md` with a planning-only P1 sequence. NV-06 starts
with one independently verified authorization result and positive, negative,
healthy and failure controls; NV-07–10 generalize that evidence into paired
trials, a small challenge, synthetic Bughunt usefulness proof and recovery.
NV-06–10 remain unchecked. Prior journal history and `docs/UI_REBUILD_PLAN.md`
are unchanged.

**Files / verification:** This planning checkpoint changes only the handoff
and this journal entry. The NV-05 commit contains the implementation and saved
gate evidence listed below. No product code or full test gate ran for this
plan; reviewed the existing validator, score, finding and event seams and ran
`git diff --check` on the planning changes.

**Risks / next step:** The current marker validator can use a caller-supplied
marker, crash confirmation can lack action linkage, and benchmark `found`
points can reflect a claim before effect confirmation. The next builder should
freeze the NV-06 acceptance matrix and construct its fixture before changing
the API or scorer. No P1 completion is claimed.

## 2026-09-23 — Complete NV-05 scoped research access and runtime capabilities

**Outcome:** NV-05 is complete on Docker-local. Scenario nodes now declare named
internal TCP services separately from host-published ports; the immutable
lifecycle recipe and equivalence digest retain them. An attacker binding or
operator can create an idempotent, expiring, single-stream lease to one service
from a selected foothold segment. The worker resolves the actual owned target
container, verifies the exact shared internal network, and owns a labeled,
resource-limited fixed-destination relay. An independently authenticated
WebSocket carries bytes through bounded Redis frames. Creation and stream
opening each spend durable NV-04 actions. Revoke, expiry, binding pause/revoke,
stop, reset, teardown and worker-loss recovery close and reclaim access.
ADR-0016 is accepted; this is a TCP relay, not SSH. A versioned, principal-
filtered capability manifest is available through REST, attacker and operator
MCP discovery, and the current Flask workspace, with CSRF-protected lease
controls.

**Files:** Scenario schema and lifecycle projection; migration `0008`, lease
model/database methods, API routes and WebSocket, worker task, Docker provider
and trusted relay script; gateway client/tools, Flask workspace and local
loopback client; two-segment fixture, isolated Compose/live verifier, focused
PostgreSQL race tests; `docs/API.md`, ADR-0016, TODO, ROADMAP, README and this
journal. `docs/UI_REBUILD_PLAN.md` and prior journal entries remain intact.

**Verification:** Final `make release-check` passed on pinned Python 3.11.14:
Ruff 0.6.9 clean, Bandit 1.9.4 with zero medium/high findings, 891 SQLite
tests passed (four PostgreSQL-only skips), 895 PostgreSQL tests passed, six
declared integration deselections on each backend, and clean Alembic plus
API/console/MCP readiness smoke. PostgreSQL tests raced lease create/claim,
revoke/connect and stop/helper-start. `make verify-nv05-live` passed: internal
fixture bytes via the declared foothold segment, wrong destination and stance
denial, filtered manifest, MCP and CSRF console control, loopback client,
mock-provider unsupported state, active revoke and expiry with reconnect
denial, binding revocation, arena and persistent system stop, stop/stream race,
killed-worker recovery, replacement reset and zero final labeled
containers/networks/volumes. Its active revoke closed in 0.34 s.
The NV-02, NV-03 and NV-04 Docker live regressions passed afterward, each with
zero final labeled resources. Evidence: `docs/verification/nv05-gates-2026-09-23.json`,
`nv05-live-2026-09-23.json`, and refreshed NV-03/NV-04 live JSON files.
`git diff --check` passed.

**Unresolved risks / next step:** Only Docker-local has live forward support;
cloud/VM providers explicitly refuse it. TCP is fixed destination and limited
to one stream, 1 MiB each direction, 90 seconds and 15 idle seconds. Model
token/cost hard caps remain unsupported for external drivers without trusted
usage. The Docker worker retains daemon authority on the trusted local host.
Next canonical task: NV-06 independent validation with positive, negative and
control fixtures linked to immutable evidence.

## 2026-09-23 — NV-05 fresh-session implementation handoff

**Outcome:** Replaced `tmp-implementationPlan.md` with a planning-only NV-05
handoff for declared foothold-scoped internal TCP access and a versioned
REST/console/MCP runtime capability manifest. NV-05 remains unchecked. The
completed NV-04 work, its live evidence, and the separate UI rebuild proposal
were committed locally as `f90d0e6`; nothing was pushed.

**Basis / files:** Read AGENTS, README, ROADMAP, TODO, relevant ADRs, the latest
journal entry and `.lab.yaml` in continuity order; inspected current provider,
binding, budget, gateway and console seams. Changed this journal and the handoff
only. No product code or verification gate changed or ran for this plan.

**Risks / next step:** The Docker foothold currently exposes `docker exec`,
not a proven SSH service. First implement and review ADR-0016 with a transport
spike that authenticates each stream and fixes its destination without widening
control-plane Docker access. Then build the durable lease, manifest and isolated
NV-05 live gate; update canonical status only after all required gates pass.

## 2026-09-23 — NV-04 durable budgets and stop controls complete

**Outcome:** Completed NV-04. The orchestrator now owns versioned action caps,
absolute deadlines, an atomic reservation ledger and sticky per-arena/system stop
gates. The account survives gateway reconnects and NV-02 replacement resets.
REST, attacker/operator MCP and the current Flask console use the same authority;
worker jobs and disposable helper starts recheck durable gates. Stop drains work,
reaper recovery settles interrupted PoC jobs, and final traces remain readable.
Unsupported token/cost hard caps refuse admission because current BYO-agent
drivers cannot supply trusted pre-execution usage bounds. ADR-0015 is accepted.

**Files:** Added migration `0007_add_budget_stop.py`, budget/stop models and
database operations, API and gateway routes/tools, worker/provider guards,
console controls, `docker-compose.nv04.yml`, `scripts/verify-nv04-live.py`,
tests and `docs/API.md`. Updated TODO, ROADMAP and README against passing gates.
The preexisting UI rebuild proposal and earlier journal entries remain intact.

**Verification:** Final `make release-check` on pinned Python 3.11.14 passed
Ruff 0.6.9, Bandit 1.9.4 (zero medium/high findings), 889 SQLite tests (two
PostgreSQL-only skips) and 891 PostgreSQL tests; each backend had six declared
integration deselections. Clean Alembic migration and API/console/MCP readiness
smoke passed. The PostgreSQL suite includes competing admission, setup-step and
stop/helper-start transactions. `make verify-nv04-live` passed with a 200/429
one-slot race, cross-process MCP budget persistence, queued-job refund,
running-job stop and cleanup, admission/stop race, killed-worker recovery,
HTTP/browser drain, system-stop restart persistence, deadline expiry and zero
final labeled resources. `make verify-nv02-live` and `make verify-nv03-live`
passed afterward. Saved evidence:
`docs/verification/nv04-live-2026-09-23.json`,
`docs/verification/nv02-regression-2026-09-23.json` and the refreshed
`docs/verification/nv03-live-2026-09-22.json` (`verified_at` is 2026-09-23).

**Risks / next step:** Current external-agent token/cost caps remain explicitly
unsupported until a driver exposes a trusted bound and usage feed. Synchronous
foothold/setup calls drain within their bounded timeout; stop does not preempt
an already running command. Docker-local is the live-verified provider. Next:
NV-05 scoped research access and runtime capability discovery.

## 2026-09-23 — NV-04 fresh-session implementation handoff

**Outcome:** Replaced the completed NV-03 `tmp-implementationPlan.md` handoff
with a concrete NV-04 plan for durable action/time budgets, explicit token/cost
accounting limits, per-arena/system stop, shared REST/MCP/console enforcement,
recovery and isolated live acceptance. NV-04 remains unchecked. The completed
NV-03 plan is preserved in commit `e778e30`; the separate UI rebuild proposal
is unchanged.

**Basis:** Read README, ROADMAP, TODO, relevant ADRs, latest journal and
`.lab.yaml`; inspected gateway process-local budgets, binding pause, setup
step accounting, NV-03 durable jobs, model usage seams, migrations, reaper and
release/live test entry points. No product code changed and no tests run for
this planning-only handoff.

**Risks / next step:** Direct REST and concurrent setup actions currently bypass
or race process-local/event-derived counters. External BYO agents lack trusted
pre-execution token/cost accounting. The next session starts with the proposed
ADR/charge matrix and PostgreSQL admission/stop races, then implements the
remaining plan and proves the live stop gate before closing NV-04.

## 2026-09-23 — Proposed full console rebuild plan

**Outcome:** Added `docs/UI_REBUILD_PLAN.md`, a proposed frontend remake with
researcher workflows, complete surface inventory, architecture and security
boundary, phased parity migration, cutover and acceptance gates. It proposes a
React/TypeScript frontend served through the existing Flask same-origin BFF.
This changes no product code or canonical NV status. A new ADR must explicitly
supersede ADR-0012's Flask/Jinja rendering choice before implementation.

**Basis:** Inspected the current WebUI routes, templates, JavaScript, CSS,
tests, ADR-0012, ROADMAP and TODO. Checked official React, Vite, React Router,
Playwright and W3C documentation for the proposed implementation and testing
approach. No usability study or runtime test was performed for this plan.

**Risks / next step:** The cost and visual direction remain provisional until a
route/action parity matrix, researcher walkthrough and two design concepts are
reviewed. Start with that phase-0 ticket; keep NV-04/NV-05 backend acceptance
separate and coordinate their new UI contracts.

## 2026-09-23 — NV-03 confined PoC execution complete

**Outcome:** Completed NV-03: durable confined Python jobs, REST/console/attacker
MCP, fixed-target Unix HTTP relay, browser proxy, worker-owned HTTP/browser
dispatch, encrypted source/results, admission slots, cancellation and recovery.
The selected-target PoC and all required live denial, interruption and cleanup
checks passed. The runner client is installed in the immutable trusted image.

**Closure failures found and fixed:** Docker archive APIs could not collect tmpfs
artifacts (use bounded trusted tar exec); proxy readiness was shorter than measured
startup; cancellation before helper creation lost its terminal state; teardown
raced in-flight helper creation; failed cleanup was not retried; expired queued
jobs retained slots; cancellation could race a claim; idempotency was not bound to
principal; the MCP verifier assumed structured rather than JSON text content.
Exit publication is now atomic and Docker exec exit status is polled after EOF.

**Files:** orchestrator models/migration/database/API/tasks/providers and trusted
runner/relay/proxy; helper_jobs.py; gateway tools; console routes/template/JS;
dedicated docker-compose.nv03.yml and live verifier; PoC/provider/gateway/migration
tests; ADR-0014 and API/operations/README guidance.

**Verification:** Final `make release-check` passed on pinned Python 3.11.14:
Ruff passed, Bandit found zero medium/high source findings, SQLite reported
879 passed/one PostgreSQL-only skip and PostgreSQL 880 passed, with six
integration deselections each. Clean migrations and API/UI/gateway smoke passed.
`make verify-nv02-live` passed after the lifecycle/worker changes.
Final rebuilt `make verify-nv03-live` passed on Docker server 29.7.2 and worker
Python 3.11.16. It exercised a useful selected-target PoC, transfer/artifacts,
positive controls for external and other-arena canaries, explicit direct-route
denials, relay rejection, browser redirects/subresources, resource pressure,
cancellation, console/MCP flows, killed-worker recovery without replay and reset
while a helper existed. Its final owned container/network/volume counts are all
zero. Sanitized IDs, image digests, outcomes and inventories are retained in
`docs/verification/nv03-live-2026-09-22.json`.

**Risks / next step:** Docker containers share the host kernel, so this remains
a Docker-local research boundary, not VM-grade hostile multi-tenancy. Raw TCP/UDP,
runtime package installs, durable aggregate budgets/system stop and general
foothold access remain unsupported or planned. Implement NV-04 next.

## 2026-09-22 — Astra review and NV-03 handoff for Sol

**Outcome:** Reviewed committed NV-01/02 status and replaced the completed NV-02
handoff with the NV-03 confined-PoC plan for Sol: durable worker-owned jobs,
target-scoped relay enforcement, bounded IO, cancellation/recovery, shared
authorization, REST/MCP/console workflow and isolated live acceptance.
NV-03 remains unchecked; no product feature is implemented by this plan.

**Files:** tmp-implementationPlan.md and this journal. The prior handoff remains
in commit 349e804. Local .lab.yaml still marks NV-02 open; canonical TODO and the
committed acceptance artifact take precedence over that stale local note.

**Verification:** Inspected delivery docs, relevant ADRs, recorded acceptance,
helper network/provider code, API/binding/gateway seams and verification entry
points. Documentation checked with git diff --check. No tests/live gates rerun;
prior passing counts remain historical evidence.

**Risks / next step:** Arena-segment attachment does not prove selected-target-only
policy, especially for arbitrary sockets/browser subrequests. Sol must implement
and prove containment, interruption cleanup and usable console/MCP behavior before
closing NV-03. Implementation and accepted ADRs remain unchanged.

## 2026-09-21 — Complete NV-02 target lifecycle and reset reproducibility

**Outcome:** NV-02 is complete. Deploy creation now persists an encrypted immutable
lifecycle recipe separately from observed runtime state, including requested versus
effective provider, compiled scenario, pinned inputs, runtime configuration, seed and
bounded readiness policy. Build reproducibility, reset eligibility and observed
equivalence are reported independently; manual setup, mutable images/builds and legacy
records remain honestly unsupported or unverified. Public projections omit environment
values, commands, seed values, readiness truth and private authorization notes.

Reset is an operator-only durable replacement operation: one atomic in-flight claim and
idempotency key produce one stable replacement UUID, destroy the source without rewriting
its record, deploy the saved recipe, compare observed baseline digests and retain links in
both audit trails. Requested and effective providers are stored separately. Duplicate
Celery delivery, lost enqueue, stale running operations and worker restart are reconciled;
expired authorization boundaries are rechecked before destructive work, and bindings or
setup consent are not copied. The console exposes lifecycle classification, observations,
operation state and replacement links with its existing CSRF boundary.

Docker-local readiness is arena-bound and bounded. Lifecycle tasks have soft/hard time
limits and SDK timeouts. Cleanup now collects removal errors, treats already-absent
resources idempotently, discovers anonymous volumes from owned mounts, avoids forcing
shared images, verifies the final inventory and retains `error_destroying` as a reaper-
retryable obligation. ADR-0013 records the replacement-reset decision.

**Files:** lifecycle manifest/service, API/tasks/provider/persistence/model and Alembic
changes under `cyber-range/services/scenario-orchestrator/`; console route/template;
`cyber-range/fixtures/nv02-reset/`; `docker-compose.nv02.yml`;
`scripts/verify-nv02-live.py`; focused API/lifecycle/migration/reaper/provider tests;
ADR-0013; operations/status docs; and
`docs/verification/nv02-live-2026-09-21.json`.

**Verification:** Final `make release-check` passed in the pinned Python 3.11.14
environment. Ruff passed; Bandit reported zero medium/high findings; SQLite reported
863 passed, one PostgreSQL-only concurrency test skipped and six integration tests
deselected; PostgreSQL reported 864 passed and six integration tests deselected. Clean
migrations and API/UI/MCP readiness smoke passed. The PostgreSQL run exercised two real
competing reset transactions and admitted one winner.

`make verify-nv02-live` passed on Docker client/server 29.7.2, API 1.55, Linux amd64.
It deployed the content-addressed synthetic fixture, mutated and recorded it, initiated
the first reset through the CSRF-protected console and the second through the API, retained
the HTTP transaction and finding after teardown, reset twice across three UUIDs with the
same observed baseline digest, verified no inherited bindings, killed the dedicated
worker during another deployment, withheld it during a queued teardown, reconciled both
records to `destroyed`, and found zero labelled containers, networks, volumes or images
across all five arenas. Two earlier attempts found and fixed local-image-ID validation and
an already-removed-network teardown race; only the final passing result is acceptance.

**Unresolved risks / next step:** Exact reset remains intentionally limited to immutable
Docker-local inputs with declared readiness; manual setup, mutable/network builds and
other providers do not claim equivalence. The next canonical item is NV-03 confined PoC
execution. It must reuse these ownership, timeout, cleanup and scope boundaries rather
than expanding participant access to the Docker control plane.

## 2026-09-21 — Astra planning handoff for Sol: NV-02

**Outcome:** Added a concrete implementation handoff for the next Sol run, scoped
to NV-02 target lifecycle/reset acceptance. The plan preserves canonical delivery
order and specifies immutable recipes versus observed state, replacement arenas
with retained evidence, durable idempotent reset operations, bounded readiness,
verified cleanup and restart/concurrency recovery. The user's explicit choice of
Sol for implementation supersedes the older Claude Code delegation instruction
for this task. No runtime feature or NV checklist item is completed by this plan.

**Files:** `tmp-implementationPlan.md` and this journal.

**Verification:** Read the delivery docs and relevant provider, persistence, build,
research-session and console ADRs; inspected manifest/preflight, API creation,
worker/reaper, Docker deploy/destroy, database/state and verification seams.
Documentation whitespace checked with `git diff --check`. No application tests,
live arenas, migrations or release gate were run for this documentation-only change.

**Unresolved risks / next step:** NV-02 remains open. Existing reset metadata is a
declaration rather than observed equivalence; provider cleanup can report success
after volume/image removal errors. Sol should implement the handoff and prove the
isolated live lifecycle path plus the supported release gate before marking NV-02
complete. NV-03 follows; NV-06 implementation still depends on the P0 runtime.

## 2026-09-16 — Complete NV-01 reproducible release/test environment

**Outcome:** NV-01 is complete. Added one documented clean-checkout command,
`make release-check`, which builds a dedicated Python 3.11.14 verifier from an
exact dependency lock, runs the source quality/security and SQLite gates, performs
clean Alembic plus API/console/MCP-gateway readiness smokes, and repeats the suite
against a disposable PostgreSQL service. The wrapper removes stale verifier state
before and after each run. CI now uses the same pinned interpreter, lock and Make
targets. Host `make check` refuses unsupported Python instead of silently using the
local 3.14 environment.

The gate consistently excludes local `.venv` and nested `venv` trees from Docker,
Ruff and Bandit, and excludes local `.env` files from the clean build context. This
fixed the review's Bandit defect and two broader variants discovered during the
first clean run. Docker/OpenTofu tests remain explicit integration work rather than
being silently counted as hermetic coverage.

**Files:** `.python-version`, `requirements-lock.txt`, `Dockerfile.verify`,
`docker-compose.verify.yml`, `scripts/release-smoke.py`, `scripts/verify-release`,
`Makefile`, `.dockerignore`, `ruff.toml`, `.github/workflows/ci.yml`,
`CONTRIBUTING.md`, `docs/OPERATIONS.md`, `README.md`, `ROADMAP.md`, `TODO.md`, and
this journal.

**Verification:** `make release-check` passed end to end on Python 3.11.14 with
Ruff 0.6.9 clean and Bandit 1.9.4 reporting zero medium/high findings. SQLite:
852 passed, 6 deselected. PostgreSQL 16.15: 852 passed, 6 deselected. The six
deselections are five tests requiring a live Docker daemon and one requiring
OpenTofu. The clean Alembic migration created the expected schema; unauthenticated
API `/health`, console `/login` with CSRF, and attacker MCP tool registration all
passed readiness smoke. `git diff --check` is part of the final handoff check.

**Unresolved risks / next step:** This gate deliberately does not mount the host
Docker socket and did not execute OpenTofu, so it makes no live arena lifecycle
claim. NV-02 is next: record target build/runtime/reset manifests and prove repeated
Docker-local deploy/reset, interrupted cleanup, and post-teardown evidence retention.

## 2026-09-07 — Reorganize research and agent-evaluation delivery

**Outcome:** Operator-requested documentation update only. Added NV-01–15 with dependencies
and acceptance criteria. P0 establishes a reproducible release/reset path, confined execution,
durable budgets/stop and scoped access. P1 strengthens independent validation and introduces
durable experiments, a small challenge library, Bughunt usefulness proof and record recovery.
P2 expands version/fix replay, fuzzing, binary/local VM and research/disclosure work only for
selected target needs. Discovery and evaluation remain first-class objectives; no platform
was archived and no new runtime/integration feature is claimed as implemented.

Reconciled stale guidance: dynamic Docker topologies, stance-scoped MCP and R1 HTTP
capture/replay are implemented. R1's old task slices remain a design/acceptance reference.
Cloud provider parity remains deferred. Existing ADRs are unchanged; this is delivery
sequencing and acceptance refinement, not a replacement for their technical boundaries.

**Files:** TODO.md (new), ROADMAP.md, README.md, AGENTS.md, docs/JOURNAL.md (new), and the
local Git-ignored .lab.yaml milestone summary. No code, infrastructure or operator data changed.

**Verification:** `git diff --check` passed. Python documentation checks found 15 unique open
NV task IDs and valid local checklist links (this journal completes the final link). Local
.lab.yaml parsed successfully. Dependencies/mapping retain R2/R3, D1–D4, E1–E5 and proof work;
implemented foundations are separate. No application tests were rerun for documentation edits.

**Review baseline, not a new full gate:** earlier today Ruff passed; source-only Bandit
(excluding .venv and nested venv) had zero medium/high findings; 121 focused tests passed.
The full Python 3.14 suite stalled in Starlette TestClient and was interrupted. Standard
make check scans an unintended nested venv. The cached Python 3.11 image lacks full test
dependencies. No main Compose stack was running, and no live arena or PostgreSQL suite was
verified. The August 18 result of 808 passes/six skips remains historical.

**Risks / next step:** NV-01 must restore the supported Python 3.11 full gate and correct
Bandit's exclusion before a professional-readiness claim. Then NV-02 proves target lifecycle
and reset; NV-09's one local agent workflow supplies evidence for continued investment.
Bughunt integration is planned, uses synthetic credentials and does not expose hidden truth
or operator-only evaluation exports to the participant.
