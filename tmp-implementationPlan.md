# Astra → Sol implementation handoff: NV-02

Prepared 2026-09-21. Status: implemented and accepted on 2026-09-21.

## Objective and authority

Complete **NV-02 — Prove target lifecycle and reset reproducibility**, the next
unchecked item in [TODO.md](TODO.md). This handoff interprets “complete the phase”
as this delivery item, not all of P0 or the evaluation workbench. NV-01 is recorded
complete; NV-03–05 follow NV-02; NV-06 implementation depends on the P0 runtime.
Do not use the September 20 brainstorm's NV-06-first implementation order.

The user explicitly selected Astra for this planning run and Sol for the next
coding run. That instruction takes precedence over AGENTS.md's older instruction
to route implementation through Claude Code. Sol should implement and verify this
handoff directly. Preserve the existing dirty worktree, including untracked NV-01
release files; they are the starting baseline, not disposable changes.

Acceptance from TODO.md:

> Repeated deploy/reset produces equivalent starting conditions; interrupted
> deploy/destroy leaves no orphan resources; evidence remains readable after teardown.

Extend pinned intake with build/dependency/runtime/configuration/seed/reset
manifests, bounded readiness and recovery. Prove one small Docker-local fixture
end to end. Other intake modes must receive honest reproducibility classifications;
this does not require making arbitrary repositories reproducibly buildable.

## Read first and preserve

Follow the repository continuity order: README, ROADMAP, TODO, relevant ADRs,
latest JOURNAL, `.lab.yaml`, then history if needed. In particular:

- ADR-0003: provider selection and idempotent, arena-scoped destroy.
- ADR-0004: SQLAlchemy/Alembic, legal lifecycle transitions, append-only events.
- ADR-0007/0008: consent-gated setup/build and existing target build pipeline.
- ADR-0011: immutable target identity, reset contract, source visibility and evidence.
- ADR-0012: thin console backed by service APIs, retained archived workspaces.

Keep deterministic evidence and validation boundaries intact. No LLM judge or Jev
integration is part of NV-02. No repository migration/history rewriting, credential
rotation, cloud provisioning, OAuth, commercial packaging, durable experiments,
PoC sandbox or global budget subsystem belongs in this implementation.

## Observed code baseline

Paths below are relative to the repo. `ORCH` means
`cyber-range/services/scenario-orchestrator`.

| Existing seam | Relevant gap observed during planning |
|---|---|
| `ORCH/research_session.py` target manifest builders | v1 records immutable source and `destroy_redeploy`; it does not prove restoration of runtime or seed state. |
| `evaluate_preflight()` | Explicitly infrastructure-only. `reset_contract` passes from declared flags; running nodes are not application readiness. |
| `ORCH/api.py` Git/OCI/bundle creation routes | SUT manifest/setup metadata is event-backed; compiled scenario is passed to Celery. Retain a durable recipe rather than depending on task arguments or mutable scenario names. |
| `ORCH/tasks.py:deploy_lab` | Marks active before research preflight; duplicate delivery and teardown overlap need safe handling. |
| `ORCH/tasks.py:destroy_lab`, `reap_labs` | Existing retry/reaper seams; raised destroy errors and restart recovery need explicit verification. |
| `ORCH/providers/docker_local.py:deploy`, `destroy` | Arena labels support cleanup. Deploy rollback discards cleanup outcome; volume/image removal errors are logged while destroy can still return success. |
| `ORCH/database.py:update_deployment` | Validates an in-memory state before committing; this alone is not an atomic concurrent transition/operation claim. |
| `ORCH/states.py` | `destroyed` is terminal. Preserve this invariant. |
| `cyber-range/webui/app.py`, `templates/arena_detail.html` | Existing preflight/target display and read-only destroyed workspace are the presentation seams. |

Planning inspection is not a complete security audit. Confirm details against code
before editing; use the existing tests and helpers rather than recreating them.

## Design decisions for this slice

### 1. Separate an immutable recipe from observed execution

Introduce a versioned lifecycle recipe and observed manifest. A focused module
such as `ORCH/lifecycle_manifest.py` is appropriate; retain backward reading of
existing `nidavellir/target/v1` records. Do not mutate old target/audit records to
pretend they contain new provenance.

The recipe must retain the validated compiled scenario, effective provider,
target identities, node image identities/platforms, effective runtime configuration,
build inputs, seed identity, setup/reset strategy and readiness policy. Resolve
named scenarios at creation and preserve their content; reset must not silently
load a subsequently edited scenario or resolve a moved branch/tag again.

Record requested and effective provider separately where needed. `MOCK_MODE=true`
is a hard override: mock results must be visibly mock, and changing environment
defaults must never cause cleanup/reset to use another backend. On incompatible
runtime configuration, refuse the operation and report the mismatch.

For every executed node, capture the actual image ID/digest and OS/architecture;
an OCI multiarch index alone is insufficient without the selected platform.
For source builds, include source identity, build strategy, Dockerfile/context
identity and available lock/base-image identities. Missing/unpinned dependencies
must produce explicit reasons, not invented provenance. A deterministic build
planner is not proof that network package resolution is reproducible.

Use separate classifications for build reproducibility, runtime reset eligibility
and observed reset equivalence. Proposed values may be small enums with reason
codes; do not collapse them into one boolean. A pinned packaged fixture can be
resettable while its original build provenance remains incomplete. Manual setup,
mutable dependencies and legacy missing recipes must be labeled unsupported or
unverified for exact reset. Ordinary exploratory work can remain available.

Keep reusable recipe data outside transient container workspaces. Use the existing
artifact/persistence conventions for immutable data; persist the digest/reference
in events. Separate protected recipe data from the redacted operator/participant
projection. Never put credentials or hidden challenge truth in public manifests,
audit payloads, SSE, URLs or errors. Do not hash low-entropy secrets as a substitute
for protecting them. Use existing encryption for necessary secret-bearing storage.

Define canonical JSON hashing and an explicit equivalence projection: include
target/image/platform, effective config, seed and policy identities; exclude arena
UUIDs, container IDs, allocated IPs/ports and observation timestamps. Store an
observed fixture state digest independently of the recipe digest. Matching input
metadata alone must not count as reset proof.

### 2. Reset means replacement with a linked new arena

Keep the original arena terminal and its evidence readable. Reset destroys the
old runtime and creates a new arena UUID from the saved recipe, with durable links
in both directions. A failed replacement leaves the old result available and a
visible failure; it never resurrects or overwrites the original result.

Implement a small durable reset operation with an idempotency key, source arena,
replacement arena, recipe digest, status/stage, bounded deadline and error/result.
A minimal SQLAlchemy record plus Alembic migration is justified for transactional
claims and retries; event records alone must not be used as a read-then-write lock.
Use a database constraint/atomic claim to prevent two in-flight resets for one
source. Allocate and persist the replacement ID once. Append audit events alongside
durable state changes. Recovery must handle a committed operation whose Celery
message was never sent as well as a message delivered more than once.

Suggested API: `POST /arenas/{id}/reset` returns an operation ID and replacement
ID; expose operation status through a small GET endpoint. Validate eligibility
before destroying anything. Accept reset of an eligible active or already-destroyed
record; reject transient states and missing/unverified recipes with actionable
errors. A concurrent conflicting request returns 409; retrying the same idempotency
key returns the existing operation. Define retry behavior after terminal failure
explicitly and test it.

Reset is an operator action in this slice. Enforce that in the API, not only the UI.
Do not copy participant tokens/bindings or setup consent blindly to the replacement;
new participant access follows existing explicit authorization. Do not create an
agent-controlled route to bypass the future NV-04 budgets. Preserve existing scoped
MCP lifecycle behavior and report unsupported reset clearly where applicable.

Snapshot policy and authorization provenance, but revalidate applicable permissions,
source-build/setup consent and effective runtime policy when a reset executes.
Never silently reopen setup egress. Do not renew an expired time box implicitly:
carry its absolute deadline and reject an expired reset; a fresh time box is a new
operator-authorized engagement.

### 3. Readiness and recovery are bounded, worker-owned operations

Keep infrastructure readiness distinct from application readiness. For the fixture,
use a declared bounded HTTP health probe and a deterministic state observation.
Probe only a validated arena node/port/path, through the provider's contained
network path; no arbitrary URLs or control-plane access to untrusted destinations.
Disable off-target redirects, cap bodies, and bound connect, request and total time.
No arbitrary host shell commands in probe/seed definitions.

Manual-setup targets may have usable infrastructure before an application exists.
Preserve that workflow, but label service readiness pending/unverified and refuse
a successful reset-equivalence claim. A reset operation completes only after the
replacement's declared readiness and baseline comparison pass.

Make deployment/cleanup operations bounded beyond a single SDK socket timeout.
Persist operation deadlines and ownership needed by worker/reaper recovery. Use
atomic state claims and coordination that prevents a still-running deploy from
creating resources after teardown has declared success. Checking the DB once at
task entry is insufficient. Account for SDK calls already in flight, late completion,
worker death, duplicate delivery and reaper races. A timeout must initiate cleanup
or leave a durable retryable cleanup obligation, not merely stop polling.

Cleanup must enumerate and reclaim all owned containers (including helpers),
networks, mutable volumes and arena-built images. Treat anonymous image-declared
volumes explicitly; they can escape a simple label-only volume query. Do not remove
shared cached images or resources owned by other arenas. Collect errors, verify
remaining owned resources, and report failure/retryable state if anything remains.
Never mark destroyed solely because removal was attempted. Interrupted creation
must be discoverable by stable ownership labels/records before ordinary task
completion. Never use daemon-wide prune or project-wide deletion to pass a test.

Do not force-remove an image used by another arena. For the first acceptance
fixture, use a retained immutable shared fixture image and disposable per-arena
runtime state. Arena-built images currently reclaimed on destroy require a proven
rebuild or an explicit retained-artifact policy; otherwise label exact reset
unsupported. Avoid adding a general artifact-retention subsystem in this slice.

## Implementation sequence

1. **Manifest and fixture contract.** Implement schema, canonical hashing,
   classification, compatibility and sanitized projections. Add a small local
   synthetic HTTP fixture with known initial data and a mutating action. Bake its
   seed into immutable inputs; no live credentials, LLM, public vulnerable service
   or new package installation is needed at runtime. Capture actual image identity.
2. **Durable recipe and operation persistence.** Wire creation paths to snapshot
   recipes; add the migration and atomic claim/recovery methods. Cover Git, OCI,
   bundle and challenge paths with either valid metadata or explicit limitations.
   Add a short ADR describing replacement reset and its lifecycle coordination.
3. **Worker/provider correctness.** Implement bounded application readiness,
   cleanup verification and interruption/race handling. Preserve existing state
   graph, provider contracts and mock behavior. Repair the observed swallowed
   cleanup failures. Test this before wiring reset orchestration.
4. **Reset service/API.** Drive the durable operation through cleanup → replacement
   deployment → readiness → observed baseline comparison. Keep side effects in the
   worker/provider and decisions in shared service code. Integrate recovery with
   the existing reaper. Record mismatch as a failed/inconclusive reset, with reasons.
5. **Console completion.** Add manifest/classification/readiness details and an
   operator reset action to the existing workspace. Show pending/failure/success
   and the link to the replacement; retain the original read-only evidence view.
   Use existing CSRF and API helpers. No lifecycle business logic in Flask.
6. **Live acceptance and handoff.** Run the checks below, fix relevant failures,
   record the evidence and only then reconcile TODO/ROADMAP/README/JOURNAL.

Likely edit areas: `ORCH/research_session.py`, a focused lifecycle service/manifest
module, `api.py`, `tasks.py`, `database.py`, `models.py`, `migrations/versions/`,
`providers/docker_local.py`, `providers/base.py`/`mock.py` for actual shared
capabilities, configuration/schema modules as needed, and the existing workspace.
Do not refactor unrelated provider implementations or split the large API as a
prerequisite. New provider methods should default to explicit unsupported behavior.

## Verification and completion gate

Extend existing relevant tests: `test_research_session.py`, `test_docker_provider.py`,
`test_deploy_observability.py`, `test_reaper.py`, `test_database.py`, `test_states.py`,
`test_migrations.py`, target-intake tests, `test_deployment_records.py`,
`test_http_transactions.py`, `test_evidence_artifact.py` and `test_webui.py`.
Add focused lifecycle/reset tests where this keeps the new behavior legible.

Required behavioral coverage:

| Case | Required result |
|---|---|
| Same input, different UUID/ports/time | Same equivalence projection; independent observed seed state agrees. |
| Changed seed, image, platform or relevant config | Different identity or explicit reset mismatch. |
| Moved Git ref/OCI tag or edited named scenario | Reset uses saved immutable inputs; unavailable artifacts fail explicitly. |
| Unpinned package/build, manual setup, old v1-only record | Honest limitation; no reproducible-reset success claim. |
| Running but unready, exited, hung, redirecting target | Bounded readiness failure; scoped cleanup/recovery; no false success. |
| Repeated reset request/task delivery | One durable operation/replacement; no duplicated infrastructure. |
| Concurrent deploy/destroy/reset/reaper | Legal atomic transitions; no late active result or untracked resources. |
| Worker death or lost enqueue during each phase | Recovery resumes or terminalizes with cleanup; persisted links survive. |
| Removal error / anonymous volume / in-use image | Visible retryable cleanup result; unrelated resources preserved. |
| Missing authorization, expired deadline, participant reset attempt | Rejected before destructive side effects. |
| Original arena destroyed and replacement created | Original findings, transaction/patch digests, trace/events remain readable and unchanged. |

Run focused tests first in Python 3.11. Then run `make check` in the supported
environment and `make release-check` for the pinned SQLite/PostgreSQL gate. The
release verifier's SQLite target already invokes the same component checks; record
where they ran rather than attempting the unsupported Python 3.14 host gate.
Use PostgreSQL tests to exercise real competing transactions, not just sequential
mock calls. Record new counts and skips; do not copy the historical 852 count.

Add a repeatable, opt-in live NV-02 acceptance command/script and document it in
OPERATIONS. The NV-01 verifier deliberately excludes live Docker tests. A passing
mock suite or skipped integration tests cannot close NV-02. `make test-integration`
currently sets `MOCK_MODE=true`: direct provider tests can still hit Docker, but
the full-stack acceptance must explicitly assert the effective live provider.

Use an isolated Compose project with dedicated DB/evidence volumes and nonconflicting
ports. Verify that effective API/worker configuration selects docker-local and
does not inherit the dev override's forced mock mode. Keep Docker privileges at
the existing boundary; do not add socket mounts to the console, gateway or target.
Do not reset the operator's running arenas or reuse their database for fault tests.

The live acceptance must:

1. Deploy the pinned fixture through the real API/Celery/worker path; inspect
   manifest and application readiness in the console.
2. Capture initial observed state, mutate the fixture and record an HTTP transaction
   plus a finding/evidence reference. Prove the state actually changed.
3. Reset through the API/UI, confirm a new linked UUID, equivalent starting state
   and no mutation residue. Repeat for at least three total deployments (two resets).
4. Interrupt deployment and teardown on dedicated test arenas; restart/reconcile
   and verify no owned resources remain after the bounded recovery period. Include
   one real process interruption, not only a mocked exception.
5. After teardown, inspect original findings, HTTP transactions, evidence hashes
   and audit/trace through the API and console. Verify cross-arena access remains
   denied and the replacement does not inherit participant credentials.
6. Record actual commands, versions/platform/image identities, arena/operation IDs,
   normalized and observed digests, failures/retries and final resource inventory.
   Retain a sanitized acceptance artifact under `docs/verification/`; do not commit
   raw response bodies, credentials or whole local databases.

Finish with `git diff --check` and a scoped diff review. Only mark NV-02 complete
after all acceptance conditions and supported release checks pass. If a required
runtime is unavailable, finish all independent work, leave NV-02 unchecked and
record the exact remaining command/blocker. Do not convert a partial result into
completion or proceed to NV-03 to obscure missing NV-02 acceptance.

## Copy/paste prompt for the next Sol run

> Implement `tmp-implementationPlan.md` to complete NV-02. I have selected Sol for
> implementation; this overrides the older Claude Code delegation instruction for
> this task. Preserve existing changes. Follow the numbered slices, implement the
> API/worker/provider and console flow, run the supported release gate and isolated
> live Docker acceptance, and fix failures within scope. Do not jump to NV-06 or
> implement later NV items. Update the plan's progress and the dated JOURNAL with
> actual results; check NV-02 in TODO only when its full acceptance is met. If an
> external permission/runtime blocks the last checks, report precisely what remains.

## Progress for Sol to maintain

- [x] Manifest/fixture contract implemented and tested.
- [x] Durable recipes, operation claims and migration verified on both databases.
- [x] Bounded readiness, cleanup and race/restart recovery verified.
- [x] Reset API and console workflow complete.
- [x] Supported release gate passes.
- [x] Live repeated reset, interruption cleanup and retained evidence proof passes.
- [x] Status docs and dated journal reconciled; next task is NV-03.
