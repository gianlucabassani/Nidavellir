# Development journal

Dated handoffs record changes and actual verification. TODO.md is the canonical ordered
work queue; ROADMAP.md retains design detail and historical milestone mapping.

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
