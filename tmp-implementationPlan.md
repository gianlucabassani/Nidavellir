# Astra → Sol implementation handoff: NV-03

Prepared 2026-09-22. Implemented and verified; NV-03 closed 2026-09-23.
Baseline: commit `349e804`, which preserves the completed NV-02 handoff.
The user selected Astra for planning and Sol for implementation. Sol implements
directly; this supersedes the older Claude Code delegation instruction.

## Objective and boundaries

Complete TODO NV-03 / ROADMAP R2: worker-owned disposable Python/PoC helpers
with CPU/RAM/PID/time limits, minimal filesystem, no external egress and explicitly
scoped arena target/file access. REST, console and attacker MCP share authorization
and audit. Acceptance requires a useful target-connected PoC, proven denial of
host/other-arena/internet/metadata access, and cleanup on stop/error.

NV-04 aggregate durable budgets/system stop and NV-05 forwards/capability discovery
remain later work. Per-job deadlines, cancellation and recovery are required now.
No cloud parity, arbitrary participant images, runtime pip/apt, general host shell,
experiments, Bughunt integration or broad API refactoring.

Read README → ROADMAP → TODO → ADR-0003/0004/0005/0011/0012/0013 →
latest JOURNAL → .lab.yaml. The local .lab.yaml still marks NV-02 open;
canonical TODO and committed acceptance evidence take precedence.

## Reviewed baseline

- NV-01/02 completion and limits are recorded in JOURNAL and
  docs/verification/nv02-live-2026-09-21.json. Historical Python 3.11.14 gate:
  SQLite 863 passed/one PostgreSQL-only skip; PostgreSQL 864 passed;
  six integration deselections each. Live reset/interruption gate passed.
  Astra did not rerun those gates during this documentation review.
- ORCH below means cyber-range/services/scenario-orchestrator.
- ORCH/api.py browser/HTTP routes currently invoke provider helpers synchronously.
  Existing target, binding and transfer helpers are integration seams.
- ORCH/providers/docker_local.py browser_visit/http_request create resource-capped
  read-only helpers attached to the selected target's arena segment. Segment
  membership does not enforce selected-target-only access. Browser redirects and
  subrequests require controls beyond initial URL validation.
- ORCH/bindings.py CAP_EXEC and attacker bindings provide existing authorization;
  operator access still requires the same containment.
- ORCH/tasks.py, database.py, models.py and ADR-0013 provide durable claims,
  deadlines, reaper and verified cleanup patterns.
- Gateway seams: services/agent-gateway/gateway/{stances,tools,rest_client,server}.py.
  Console seams: cyber-range/webui/app.py and templates/arena_detail.html.
- Tests to extend: test_agent_binding, test_agent_gateway, test_http_primitive,
  test_http_transactions, test_docker_provider, test_reaper, test_migrations,
  test_lifecycle_reset and test_webui.

This is scoped planning inspection, not a security certification.

## Design contract

### 1. Durable job and worker ownership

Introduce a focused execution service and SQLAlchemy job record/Alembic migration.
Record arena/effective provider, principal/binding identity, immutable input digest,
runner image/platform, resolved target policy, limits, absolute deadline, state,
worker claim, result/evidence references and cleanup obligation.
Suggested states: queued, running, succeeded, failed, timed_out, cancelled.
Process outcome and verified resource reclamation are separate.

Suggested routes: POST /arenas/{id}/poc-jobs; scoped GET list/detail/result;
POST /arenas/{id}/poc-jobs/{job_id}/cancel. Idempotency keys prevent duplicate
execution; reuse with changed inputs conflicts. Bound per-arena/global concurrent
jobs atomically, not with process-local counters.

API validates/enqueues; workers alone create/execute/remove new helpers.
Recheck active arena, effective provider, binding/pause/revocation and deadline
before execution. Never serialize raw API keys. Authorize result reads and cancel
as well as creation; reject cross-arena job IDs. Retain authorized archived reads.

Recover lost enqueue and stale claims. An interrupted PoC may have target side
effects: do not blindly rerun it after worker death. Terminalize interrupted work,
retain available evidence and reconcile cleanup. Stable job/arena labels discover
resources created before DB persistence. Coordinate admission/creation with
destroy/reset, including in-flight SDK calls and late completions. Entry-time
checks, finally blocks and Celery revoke alone do not establish this guarantee.

### 2. Enforced confinement

Trusted operator-configured immutable Python runner, fixed entrypoint, non-root
UID, all capabilities dropped, no-new-privileges, default seccomp, read-only root,
bounded tmpfs workspace and CPU/memory/PID/time limits. No socket/host mounts,
devices, privileged mode, host networking, inherited secrets, caller container
flags or arbitrary images. Python language restrictions are not the boundary.
Record actual image/platform; no implicit network install/pull during execution.

Default networkless. For the first useful slice, allow Python HTTP(S) against an
explicit arena target/port through a trusted bounded worker-owned relay on an
isolated helper network. Resolve destination from live arena ownership, never
caller IP/URL. Do not place arbitrary Python on the target's ordinary arena segment
or share its network namespace.

The relay must allow only the selected destination, with no open CONNECT,
arbitrary upstream proxy, DNS resolver, package-mirror or control-plane access.
Enforce host/gateway/metadata/external/cross-arena/nonselected-node denial even
for direct Python sockets. Address IPv4/IPv6, redirects/subresources, DNS rebinding,
alternate address forms and proxy-environment bypass. An internal Docker bridge
alone is not proof of host isolation.

Document supported HTTP(S) behavior and unsupported raw TCP/UDP explicitly.
If the relay cannot enforce policy, keep execution networkless until corrected;
networkless-only execution does not close target-connected acceptance.
Add an ADR for the implemented enforcement/ownership contract and shared-kernel
limitations. Do not silently widen API Docker authority or add broad privileged
host firewall access as an implementation shortcut.

### 3. Input/output and evidence

Bound UTF-8 source and explicitly selected files; fixed argv/workspace paths,
no host shell interpolation. Reuse /opt/nidavellir-transfer via validated copying,
not shared host/foothold mounts. Reject traversal, links, special files, oversized
archives and unsafe concurrent changes. Hash exactly the bytes executed.
No unrestricted foothold filesystem or hidden truth.

Bound stdout/stderr during production/collection and Docker log storage, not
only by slicing a final in-memory string. Bound artifact bytes/count and reject
links/special files. Use protected evidence conventions for source/results;
audit and trace store metadata/hashes, not bodies/secrets. Results survive helper
and arena teardown; escape output when rendering.

### 4. Shared REST/MCP/console behavior

Use one authorization/policy/audit contract for PoC, HTTP/browser and transfer.
Extend CAP_EXEC or introduce an explicit capability; attacker/operator supported,
other stances denied unless deliberately authorized. Preserve binding pause.

Move HTTP/browser helper lifecycle needed by this contract to the worker boundary.
Preserve existing REST/MCP result contracts through bounded waits or compatible
operation handling. Check browser-validator callers too. Enforce target policy
for browser subrequests and redirects. Transfer keeps its safe bounded contract;
avoid rewriting the whole subsystem.

Add thin MCP submit/status/result/cancel tools and console source editor/upload,
target selection, limits, run/status/cancel/output in the existing workspace.
Use CSRF and current event/polling patterns. Users must author and run a small
PoC without leaving the console; archived arenas retain results with no live
actions. Gateway process-local aggregate budgets remain limited until NV-04.

## Implementation sequence

1. Job/API/policy/limits contract and ADR; authorization tests.
2. Trusted runner/relay, bounded IO and explicit unsupported/mock provider paths.
3. Durable worker claims, cancellation, recovery and destroy/reset coordination.
4. Shared HTTP/browser/file boundaries and regressions.
5. REST/MCP/console workflow and retained evidence.
6. Isolated live acceptance, release/regression gates, truthful status update.

Maintain progress below. Preserve accepted NV-02 semantics.

## Verification and completion

Automated tests: missing/wrong/revoked/paused bindings; cross-arena reads/cancel;
idempotency/duplicate delivery; competing admission; lost enqueue/worker death;
deadlines; cancel/finish/reset/destroy races; resource/output limits; cleanup errors;
path/link/archive attacks; input identity; relay/socket/redirect policy; unsupported
providers; CSRF/output escaping; retained evidence and compatibility.
Exercise migrations on both databases and real PostgreSQL competing transactions.

Run focused tests on supported Python 3.11, then make release-check (includes
make-check components). Record actual new counts/skips. Rerun make verify-nv02-live
when helper/cleanup/lifecycle behavior changes.

Add make verify-nv03-live with isolated Compose project, dedicated DB/evidence
volumes and nonconflicting ports; use scripts/verify-nv02-live.py as a pattern.
Assert effective docker-local. No operator DB/arenas, daemon-wide prune or cloud.
Required live checks cannot silently skip:

1. Python accesses allowed synthetic fixture; retain source/input/output identity.
2. Direct sockets and relay attempts to host gateway/published services, control
   plane, second arena, nonselected node/port, internet canary, metadata and IPv6
   fail. Use controlled reachable canaries/positive controls, so unavailable
   services do not masquerade as enforced denial. No real metadata/secret access.
3. Browser redirects/subresources remain scoped; normal HTTP/browser/transfer
   work through actual API/worker paths.
4. Infinite loop, fork/memory/output pressure, exception and cancellation terminate
   within limits with verified helper/relay/network reclamation.
5. Kill dedicated worker during execution; restart/reconcile. Race reset/destroy
   with execution and verify no late helper or orphan.
6. Console author/run/cancel and real attacker MCP workflow pass, including
   cross-arena denial. Read result hashes/audit after teardown.
7. Save sanitized docs/verification artifact: versions/image IDs, arena/job IDs,
   deadlines/outcomes, canary controls and final owned-resource inventory.

Close NV-03 only after full acceptance. If runtime/permission blocks a required
gate, leave it unchecked and record exact remaining command/limitation.
NV-04 follows completion; do not implement it to obscure incomplete NV-03.

## Progress

- [x] Job/policy contract and ADR.
- [x] Confined runner/relay and bounded IO.
- [x] Worker/reaper/cancel/lifecycle recovery.
- [x] Shared primitives and REST/MCP/console.
- [x] Supported release and NV-02 regression gates.
- [x] NV-03 live acceptance evidence.
- [x] TODO/ROADMAP/README/JOURNAL reconciled.

## Launch prompt for Sol

> Complete NV-03 using tmp-implementationPlan.md. I select Sol to implement
> directly, overriding the older Claude Code delegation instruction. Follow
> continuity docs, preserve existing changes, implement the complete worker-owned
> confined PoC workflow across API/MCP/console, and prove containment/recovery with
> the supported release gate and isolated live acceptance. Update progress and
> JOURNAL; mark NV-03 complete only after acceptance passes. Keep NV-04 and later
> implementation out of scope. Do not commit or push unless requested.
