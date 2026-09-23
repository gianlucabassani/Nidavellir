# NV-04 implementation handoff — durable budgets and stop controls

Prepared 2026-09-23. **Implemented and verified 2026-09-23.** This remains the
historical handoff; completion evidence is in `docs/JOURNAL.md` and
`docs/verification/nv04-live-2026-09-23.json`.
Baseline: commit `e778e30` completed NV-03. The completed NV-03 handoff is
recoverable from that commit. Uncommitted `docs/UI_REBUILD_PLAN.md` and its
`docs/JOURNAL.md` entry belong to the separate console-rebuild proposal; preserve
them while implementing NV-04. The canonical roadmap order still names NV-04
next. This file is the handoff for a fresh implementation session.

## Objective and acceptance

Complete `TODO.md` NV-04 / `ROADMAP.md` R3: persist and atomically enforce
action and wall-clock budgets across gateway reconnects, concurrent REST/MCP/UI
requests, API/worker restart and arena reset. Add durable per-arena stop and
system-wide emergency stop. Stop must reject new work, cancel or drain running
work, reclaim disposable helpers and retain final traces/evidence. A budget-
constrained job must refuse to start when the requested token or cost limit
cannot be enforced from observable driver usage.

Acceptance is behavioral: reconnect cannot restore spent budget; two competing
requests cannot reserve more than the cap; stop racing admission/helper creation
leaves no late helper; restart preserves the latch and budget; final state and
evidence survive. Test these with real PostgreSQL transactions and a separate
Docker-local live gate, not only mocks.

## Scope and boundaries

- The orchestrator/database is the budget and stop authority. The gateway is a
  client and trace source, never the sole enforcement point. Direct REST and
  console calls must pass the same guardrails as MCP.
- Cover active research actions: foothold exec, HTTP/request/replay, browser,
  PoC submission, transfer, MITM observe, finding submission and configurator
  execution/upload/approved steps. Document each charge and exemption. Bounded
  status/result/event reads and cancellation/stop controls remain usable when a
  budget is exhausted. Do not let a read endpoint mutate target state.
- Keep NV-03 PoC admission slots and per-job limits; NV-04 adds an aggregate
  allowance and stop epoch around them. Keep NV-02 immutable reset/evidence
  semantics. Reset does not silently replenish an engagement's budget.
- Per-arena stop freezes research without destroying the arena. Explicit
  destroy/reset remain lifecycle operations. Existing per-binding pause remains
  a narrower reversible control; it must not be presented as the arena or
  system emergency stop.
- No NV-05 SSH forwards, capability manifest, broad frontend rewrite,
  multi-tenant identity, external cloud parity, or NV-07 experiment scheduler.
  The current Flask console receives functional NV-04 controls; the proposed
  `docs/UI_REBUILD_PLAN.md` may later re-render the same API contract.

## Reviewed baseline and seams

- `gateway/tools.py` has process-local `GatewayContext.step_budget` and
  `steps_used`. `_check_budget` runs before selected tools and increments happen
  after success. Reconnecting, a second process or concurrent calls can evade
  the limit. Some reads currently consume this local counter; define the new
  authoritative policy deliberately rather than preserving that accident.
- `api.py` enforces agent binding and per-binding pause via `_require_binding`,
  but operators bypass bindings. `setup_phase.py` derives step use from events;
  the read/check/execute/event sequence is not an atomic reservation. The
  orchestrator's `/exec` route runs synchronously and uses provider timeouts.
- NV-03 `PocJob` already has durable admission/claim/cancel/cleanup and stable
  resource labels. `tasks.run_poc_job` checks arena/binding/deadline before
  execution; `reap_labs` recovers interrupted jobs. Extend these seams rather
  than starting a second disposable-helper lifecycle.
- `models.py`, `database.py` and Alembic support SQLite + PostgreSQL. The next
  migration follows `0006_add_poc_jobs.py`. `events` is append-only audit;
  encrypted PoC source/results and archived reads already exist.
- The reference Claude Code harness reports usage/cost *after* a run. BYO MCP
  agents do not provide trusted pre-execution model accounting. Display this as
  unknown; a token/cost-constrained external-agent run must refuse to start.

Read before implementation: `README.md` → `ROADMAP.md` → `TODO.md` → ADRs
0002/0004/0005/0011/0013/0014 → latest `docs/JOURNAL.md` → `.lab.yaml`.
Read `docs/UI_REBUILD_PLAN.md` only for the parallel UI proposal. Consult git
history if these disagree with code. The old Claude Code delegation note in
AGENTS.md was superseded for direct implementation by the prior handoff; the
fresh session should follow the user's current instruction on how to implement.

## Design contract

### 1. Durable policy, identity and accounting

Add a focused budget/stop service and a reviewed ADR. Persist a versioned
policy at arena creation: action cap, wall-clock deadline, optional token/cost
caps, subject scope and accounting capabilities. Set a bounded default for new
engagements; classify pre-NV-04 arenas explicitly as legacy/unbounded rather
than silently claiming they are enforced. A policy change needs operator
authorization, a recorded reason and a new policy version; no arbitrary
increase by the agent or a reconnect.

Choose a stable budget scope that survives gateway reconnects and replacement
reset. An arena-wide account is mandatory for shared human/agent research;
per-principal/binding accounts may add narrower caps. Carry the scope across
NV-02's source→replacement lineage. A genuinely new evaluation trial can start
a new scope only through an explicit future experiment policy, not because a
UUID changed. Bound the effective wall-clock deadline by deployment expiry.

Add SQLAlchemy/Alembic records for policy/account, reservation ledger and
stop latch/epoch. A reservation has a unique caller action/idempotency key,
arena/scope, actor/role, action kind, requested units, deadline, state and
outcome reference. Never store raw API keys, secrets, command/source bodies or
model prompts in budget/audit rows. Return a stable action ID to callers and
make retries with the same ID return the same decision/result or a clear
in-progress/unknown state; reject key reuse with different input.

In one DB transaction, check active arena, binding, global/arena stop epoch,
deadline, caps and current reservations; reserve across all applicable
accounts; then publish the action. PostgreSQL row locks or conditional updates
and SQLite's write serialization must give the same no-overcommit result.
Use a single lock/compare order for global latch, arena latch, accounts and
job admission to avoid deadlocks. A failed or unknown outcome cannot be
blindly refunded: settle known no-execution failures by release, charge known
executed actions, and retain an `unknown/reconcile_pending` obligation for
ambiguous side effects. Reaper reconciles by durable action ID and resource
labels. Invariant: `spent + reserved <= cap` after every transaction.

### 2. Wall-clock, token and cost policy

Wall-clock is a persisted absolute UTC deadline, checked at admission and
worker claim; clamp every child operation's own timeout to remaining time.
Expiry latches the relevant scope and initiates the same stop/drain path; a
process clock, gateway reconnect or queued job cannot extend it. Use a
consistent database time source or explicitly test clock skew.

For token/cost limits, first enumerate actual model drivers and what they can
observe and bound. Record trusted provider usage when available, distinguish
input/output tokens, and version any price table used for cost. A hard cap
requires a conservative preflight reservation based on a known max-token
request and known price, then reconciliation to observed usage. If either is
unavailable, reject the constrained start with an explicit capability error.
Post-run CLI self-reports may be retained as *observed metadata* but cannot
serve as a pre-execution hard cap. Do not invent a zero cost, estimate as
authoritative, or permit silent unlimited fallback.

### 3. Stop semantics and recovery

Persist a monotonically increasing stop epoch and sticky state for each arena
and the system. Arena stop is operator/admin-only; system emergency stop and
clear are admin-only. API responses distinguish `stopping` (drain pending),
`stopped` (verified), and a retryable cleanup error. A clear/re-arm is explicit
and allowed only after active reservations/jobs and cleanup obligations are
reconciled; it creates a new epoch and audit event. Never auto-clear on restart.

Stop and action reservation must serialize on the same durable gate. After the
stop commit, no new action or helper may start. Work already admitted receives
a cancellation signal and must recheck the epoch immediately before side
effects and after any slow provider create call. Request cancellation for all
PoC/HTTP/browser jobs, then wait for or reconcile their labelled containers,
volumes and networks. Bound the drain; retain `stopping` and reaper retries if
cleanup cannot be verified. Do not use a Celery revoke, event-only pause or
best-effort process-local flag as the stop guarantee.

For synchronous foothold commands and setup steps, define the provider's
interrupt capability and a strict maximum remaining runtime. If a command
cannot be preempted safely, report that the stop is draining until its bound
expires; do not claim instant termination. Preserve captured output and final
event/trace once. Stop should not destroy the target or erase evidence.

Reaper must recover a lost stop message, stale reservation/worker claim and
incomplete cleanup. Unknown possibly executed actions are never replayed.
Destroy/reset/TTL must coordinate with the latch and release or carry scope
according to the policy, without accidentally reopening a stopped arena.

### 4. Shared REST, MCP and console contract

Suggested routes: scoped `GET /arenas/{id}/budget`, operator policy/status
projection, `POST /arenas/{id}/stop`, `POST /arenas/{id}/resume`, admin
`GET/POST /system/emergency-stop` and explicit clear. Name and authorize the
final routes consistently with the current API. Agent reads expose only their
own allowance and permitted metadata; no cross-arena budget or stop leakage.
Stop and clear calls require an idempotency key and audited actor/reason.

Put the reservation gate in orchestrator service methods called by every
chargeable REST route, including calls made through the Flask console and MCP.
The gateway may show a local warning but cannot decide admission. Add thin
MCP status access and show remaining action/time allowance in the existing
workspace with a stop control and distinct binding-pause state. Use the
existing CSRF boundary. Stream budget/stop changes through metadata-only
events/SSE; archived records show final policy, consumed units and reason.
Keep status/result/cancel and operator stop reachable after exhaustion.

## Implementation sequence

1. Write ADR and charge matrix: action kinds, subject scopes, retry/refund
   rules, legacy migration, stop/resume semantics and unsupported accounting.
2. Add migration/models/service for policy, reservations and stop latches;
   prove SQLite and PostgreSQL competing admissions and stop races first.
3. Wire authoritative admission/settlement into REST actions, especially
   synchronous exec/setup and NV-03 job enqueue/claim/finish. Add reaper
   reconciliation and reset lineage handling.
4. Add per-arena and system stop/drain/re-arm, provider cancellation where
   possible, and verified helper reclamation. Preserve final evidence/trace.
5. Update gateway to use server decisions, add thin MCP status, console
   controls/projections and documentation. Keep the UI rebuild proposal
   separate; use the shipped Flask workspace now.
6. Build isolated live acceptance, run the supported release and NV-02/NV-03
   regressions, write evidence and reconcile TODO/ROADMAP/JOURNAL only on pass.

## Verification and closure gate

Automated tests must cover: missing/revoked/paused/wrong-stance bindings;
direct REST versus MCP/UI parity; operator/admin stop authorization and CSRF;
no-action/read exemptions; idempotency conflicts; competing admission and
stop versus reservation on real PostgreSQL; SQLite equivalence; queued/running
worker death; duplicate delivery; timeout/clock skew; no-execution refund;
ambiguous execution retaining a claim; token/cost unsupported refusal;
scope retention across reset; archived reads; and no event/trace body leakage.

Add `make verify-nv04-live` with a dedicated Compose project, DB/evidence
volumes and nonconflicting ports. Use controlled synthetic Docker-local
fixtures and do not touch the operator's stack. Required live checks:

1. Start a bounded arena, consume actions through two gateway processes and
   direct REST/console; reconnect and prove the same remaining count.
2. Fire simultaneous requests with one slot left; exactly one executes.
   Repeat with a stop racing enqueue and a slow helper create.
3. Run a long PoC plus HTTP/browser helper, trigger per-arena stop, verify
   terminal outcomes, no late helpers, bounded drain, final result/audit/trace
   and zero owned container/network/volume leftovers.
4. Restart API, gateway and worker while system stop is latched; prove no new
   action executes, reaper finishes pending cleanup, and only admin explicit
   clear after reconciliation reopens a new epoch.
5. Expire wall-clock time during queued/running work; assert no deadline
   extension, no replay and correct remaining/final state. Test a second arena
   and the scope of per-arena versus system stop.
6. Request token/cost-capped work through a driver without enforceable usage;
   prove it is refused before side effects and reported as unsupported.

Save a sanitized `docs/verification/nv04-live-YYYY-MM-DD.json` with versions,
policy/epoch, action IDs, race outcomes, stop/drain states, retained evidence
digests and final owned-resource inventory. Run focused tests on Python 3.11,
`make release-check`, `make verify-nv02-live` and `make verify-nv03-live` after
touching lifecycle/helper paths. Record actual counts/skips and errors. Do not
mark NV-04 complete if the live stop or PostgreSQL race gate is unavailable;
write the exact blocker and remaining command instead.

## Progress for the new session

- [ ] ADR and charge/accounting policy.
- [ ] Durable schema and atomic reservations on both databases.
- [ ] Shared REST/MCP/console enforcement and time/token/cost capability behavior.
- [ ] Arena/system stop, drain, recovery and reset integration.
- [ ] Focused tests and full pinned release/NV-02/NV-03 regression gates.
- [ ] Isolated NV-04 live acceptance evidence.
- [ ] TODO/ROADMAP/README/JOURNAL reconciled against acceptance.

## Fresh-session launch prompt

> Implement NV-04 using `tmp-implementationPlan.md`. Read the continuity docs
> in order, preserve the separate uncommitted UI rebuild proposal, and keep
> `TODO.md` NV-04 unchecked until the PostgreSQL concurrency and isolated live
> stop/recovery gates pass. Implement durable orchestrator-owned budgets and
> per-arena/system stop for REST, MCP and the current console; reject
> token/cost-constrained work when accounting is unenforceable. Run the pinned
> release and NV-02/NV-03 regressions, save sanitized NV-04 evidence, update
> the journal and status only after acceptance. Do not commit or push unless
> I ask.
