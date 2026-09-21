# ADR-0013: Replacement reset with immutable recipes and observed equivalence

- **Status:** Accepted (2026-09-21)
- **Date:** 2026-09-21
- **Deciders:** Gianluca Bassani

## Context

ADR-0011 records immutable target identities and declares `destroy_redeploy` as
the reset strategy. That declaration does not prove that a deployment can be
recreated, that its application is ready, or that its starting state matches a
previous run. Reusing an arena record would also mix evidence from two distinct
runtime instances. Celery delivery, worker termination and concurrent teardown
make a read-then-write reset flow unsafe.

## Decision

A reset creates a replacement arena with a new UUID. The source arena becomes a
terminal read-only record, retaining its events, findings and evidence. Both
records receive append-only links through one durable reset operation.

At initial creation Nidavellir snapshots a versioned lifecycle recipe containing
the resolved scenario, effective provider, target and runtime identities, relevant
configuration, seed description and bounded readiness policy. Its canonical
equivalence projection omits allocated identifiers, addresses, host ports and
timestamps. Build reproducibility, reset eligibility and observed equivalence are
separate classifications. Mutable dependencies and manual setup remain usable for
research but cannot claim exact reset.

Reset operations have an idempotency key, a stable replacement UUID, a deadline,
stage and result. A database unique claim allows one in-flight reset per source.
The worker destroys through the original effective provider, deploys the saved
scenario without reloading its registry entry, performs an arena-scoped readiness
probe, captures actual runtime image/platform state, and compares the observed
baseline digest. A mismatch is a failed reset, not success with a warning.

Deployment and teardown claim legal states atomically. If deployment finishes
after another task has moved the record out of `deploying`, its resources are
cleaned rather than publishing a late `active` state. Docker cleanup enumerates
all arena-labelled resources plus anonymous volumes proven to have been mounted
by an owned container; it verifies the final inventory and reports retryable
failure when resources remain.

Only operators may request reset. Agent bindings and setup egress are not copied.
An expired engagement is not renewed by reset. Existing v1-only records remain
readable and are explicitly classified as unsupported for reset.

## Consequences

- Evidence retains an unambiguous runtime identity and survives infrastructure.
- A reset can be retried after lost message delivery without allocating a second
  replacement.
- Exact reset is intentionally narrower than ordinary deployment. A target can
  remain useful while honestly labeled unverified or unsupported.
- Docker-local is the first live implementation. Other providers inherit explicit
  unsupported lifecycle methods until they can supply equivalent evidence.
- The live acceptance gate needs trusted access to the local Docker socket in its
  isolated orchestrator and worker; no participant container receives that access.
