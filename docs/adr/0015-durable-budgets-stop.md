# ADR-0015: Orchestrator-owned action budgets and stop gates

- **Status:** Accepted; NV-04 acceptance gates passed 2026-09-23
- **Date:** 2026-09-23

## Context

The MCP gateway's step counter is process-local. Reconnects, concurrent REST
calls and direct console use bypass it. NV-03 jobs already have durable helper
leases, but admission does not share a stop gate with research actions.

## Decision

The orchestrator stores one versioned action account and deadline per new
engagement, a reservation ledger, and persistent system and arena stop gates.
Reset replacements share the source account and inherit its stop state. A
PostgreSQL row update (or SQLite's writer lock) serializes admission in the
order system gate, arena gate, account. An action reserves one unit before
execution. Successful responses spend it, rejected requests release it, and
ambiguous server failures spend it without replay. Events contain action IDs,
kind and outcome, never bodies or API keys. An explicit `X-Action-Key` binds a
retry to the same request digest; reuse returns the prior action's state.
Confined PoC submission holds its reservation through the durable worker job:
queued cancellation releases it, while a claimed or uncertain execution is
charged. A reaper closes any terminal job whose settlement was interrupted.

| Action | Aggregate charge |
|---|---:|
| exec, MITM observe, browser, HTTP request/replay, PoC submission | 1 |
| foothold upload/download, finding submission, setup step/upload/run/propose | 1 |
| bounded status/result/event reads, cancellation, stop/resume, binding controls | 0 |

The initial cap is `ARENA_ACTION_BUDGET` (default 1000, bounded to 1–100000).
The account deadline cannot exceed deployment expiry. Operators can revise the
cap and deadline with a reason, a new version and an audit event; the cap cannot
fall below spent plus reserved. Existing arenas without an account are reported
as legacy and their research actions fail closed until replaced.

External BYO MCP agents do not expose trusted pre-execution token or cost
usage. A requested token or cost cap is rejected before work starts. Reported
usage from external drivers may be metadata, but cannot satisfy a hard cap.

An operator can stop an arena; an admin can stop the system. The sticky epoch
blocks new reservations and helper admission, requests helper cancellation and
remains `stopping` until reservations and labelled helper cleanup reconcile.
The reaper continues incomplete drains. Resume is explicit after verification.
Stop and clear require a durable idempotency key bound to scope, actor, command
and reason; retries return the original epoch and conflicting reuse is refused.
Synchronous provider commands drain within their existing timeout; a stop does
not claim instant process preemption. Stop never deletes evidence or the arena.
The worker holds the system and arena gate lock across each disposable helper
create/start call. Stop waits for an in-progress Docker call, then blocks the
next one. This closes the check-then-create window without granting Docker
authority to the API or participant.

## Consequences and acceptance boundary

REST, MCP and Flask call the same orchestrator service. Gateway local warnings
remain optional secondary limits and cannot grant admission. This decision is
accepted as NV-04 complete after PostgreSQL admission/stop races, the isolated
Docker live gate, the pinned release gate and NV-02/NV-03 regressions passed on
2026-09-23. See `docs/verification/nv04-live-2026-09-23.json` and the dated journal.
