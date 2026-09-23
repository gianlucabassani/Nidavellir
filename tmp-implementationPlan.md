# NV-05 implementation handoff — scoped research access and runtime capabilities

Prepared 2026-09-23. **Planning only: NV-05 remains unchecked.** The completed
NV-04 implementation and its verification evidence are in local commit
`f90d0e6`; this file replaces its handoff. Do not reset or discard that commit.
The separate `docs/UI_REBUILD_PLAN.md` proposal remains a later UI track.

## Objective and acceptance

Complete `TODO.md` NV-05 and the remaining scoped-forward part of `ROADMAP.md`
R3. A bound attacker and a human operator must be able to open a short-lived,
audited connection from one selected foothold to one declared internal TCP
service in the same arena. Revoke, expiry, stop, reset and teardown must close
the connection and reclaim every helper. Other destinations must fail from the
actual data path, including direct REST calls that bypass the MCP gateway.

Publish one versioned, principal-filtered runtime capability manifest through
REST, the current Flask console and MCP. It must tell a caller which operations
are supported, ready, limited or unavailable for this arena and provider,
including recording, budgets, stop state and unsupported token/cost accounting.
It must not reveal hidden truth, another arena's details or operator-only data.

The live acceptance gate must prove that a client reaches a fixture service
which is reachable through the authorized foothold path, then loses access on
revoke/expiry. It must also prove denial of peer, other-arena, host, control-plane,
internet and metadata destinations and zero leftover labeled resources.

## Continuity and verified baseline

Read `AGENTS.md`, then `README.md` → `ROADMAP.md` → `TODO.md` → relevant ADRs
0002/0003/0004/0005/0011/0012/0013/0014/0015 → latest `docs/JOURNAL.md` entry →
`.lab.yaml`. Consult `git log` where status sources disagree. Read
`docs/SECURITY.md`, `docs/API.md` and `docs/UI_REBUILD_PLAN.md` for the relevant
surface, then inspect the code seams named below. The user's instruction to
build directly supersedes the Claude delegation note in `AGENTS.md`.

NV-04 passed `make release-check` on pinned Python 3.11.14 (889 SQLite tests,
891 PostgreSQL tests, six integration deselections on each backend), the isolated
`make verify-nv04-live` gate, and NV-02/NV-03 live regressions. Evidence is in
`docs/verification/`. Treat that as a recorded baseline, not proof that NV-05
works. Docker-local is the live provider; mock may report capabilities but must
not pretend to furnish a real forward. Cloud and VM parity remain deferred.
The ignored local `.lab.yaml` still groups NV-04–05 as unchecked; `TODO.md` and
the dated journal are the current status sources.

The current Docker foothold's displayed “SSH command” is actually `docker exec`;
there is no proven SSH daemon or SSH tunnel. Do not implement a UI label or MCP
tool that claims an SSH forward until a real SSH transport is established. An
authenticated fixed-destination TCP forward is an acceptable first Docker-local
implementation if ADR-0016 records its transport and limitations explicitly.

## Scope and security contract

- First workflow: an `attacker`-stance binding (or operator) selects one foothold
  and one named internal TCP service on an arena target. The service identity
  and port are declared in the versioned scenario, not supplied as a raw URL,
  hostname, IP or arbitrary port in the forwarding request. The foothold and
  target must share an allowed arena segment; the provider resolves the current
  target container/IP just before helper creation and verifies arena labels.
- Add a schema field for internal forwardable services, separate from `ports[]`
  if `ports[]` publishes host ports. Preserve it in NV-02's immutable recipe and
  reset equivalence projection. Build a two-segment fixture with a service that
  is not host-published, so the acceptance test cannot pass through an existing
  browser or host-port shortcut.
- Only TCP is in scope. No SOCKS proxy, dynamic destination, DNS lookup from the
  participant, reverse tunnel, UDP, raw host socket, general network pivot, or
  arbitrary SSH access. Do not extend the existing package mirror into a
  general proxy. Do not attach an untrusted runner to a broad arena bridge.
- The control plane authenticates every lease operation and byte-stream
  connection. A bound agent needs a new server-side `CAP_FORWARD` allowed only
  for the attacker stance; a paused/revoked binding closes access. The gateway
  tool allow-list is secondary. Operators may create/revoke through the same
  REST contract. Never put an API key or stream credential in a URL, event,
  audit payload or trace.
- A forward lease has one fixed destination, creation idempotency key, owner,
  binding generation, expiry no later than arena/budget deadline, limits on
  concurrent streams, bytes and idle time, and a durable state/cleanup result.
  A stream requires a fresh stop/binding/lease check. Charge lease creation and
  stream opening through NV-04's orchestrator budget authority, not a gateway
  local counter; do not leave a long-lived stream as unlimited work after its
  admission action. Reject unsupported accounting explicitly.
- Stop and helper start serialize on NV-04's system→arena gate order. After a
  stop commits, no new relay or stream may start. Existing streams are closed;
  a slow helper create cannot publish a late usable forward. Reset/destroy/TTL
  cancel leases before the source arena disappears. Reaper reconciles stale
  leases and label-owned helper resources after worker death. Final status and
  body-free audit events remain readable after teardown.
- A local client may bind only loopback for the user's application and carry
  bytes over an authenticated API stream. The API must never expose a raw
  unauthenticated host port. MCP and Flask manage leases and show the connection
  command/status; MCP text tools are not a binary tunnel. If the selected
  transport cannot enforce auth and scope at connection time, stop and revise
  the ADR before adding it to the product.

## Architecture decision to settle first

Write ADR-0016 before provider code. Prove a small Docker-local transport spike:
from an independently authenticated client, reach a fixed service through an
owned helper from the selected foothold's segment, while the control-plane and
other segments remain unreachable. Decide how the API carries bytes to the
worker-owned relay without granting Docker socket authority to the API or
placing a generic dual-homed router on a control network. Document where each
socket lives, which process validates the destination and principal, how a
revocation interrupts active streams, and how resource labels are reclaimed.
Reject the design if it relies only on client-side target filtering or a
localhost port with no per-connection authentication.

The intended public contract is:

| Surface | Operation | Authority |
|---|---|---|
| REST | `GET /arenas/{id}/capabilities` | Orchestrator returns a filtered v1 manifest. |
| REST | `POST /arenas/{id}/forwards` | Resolve declared service, reserve budget, create durable lease. |
| REST | `GET /arenas/{id}/forwards`, `GET .../{forward_id}` | Owner/operator sees lease and cleanup state. |
| REST | `POST .../{forward_id}/revoke` | Idempotent revoke; closes active streams. |
| Authenticated stream | `.../{forward_id}/connect` | Recheck principal, binding, stop, expiry, byte/connection limits. |
| MCP | `runtime_capabilities`, `open_forward`, `forward_status`, `revoke_forward` | Thin client to REST; attacker tools only for forward operations. |
| Flask | Workspace capability and forward controls | Same REST contract, CSRF-protected writes, no API key in browser. |

An HTTP WebSocket stream plus a small loopback-only client is a candidate, not
an assumed implementation. The ADR must show the actual relay path before the
API route or client command is treated as settled. Keep routes/schema versioned
and use the existing `X-Action-Key`/idempotency conventions where applicable.

## Runtime capability manifest

Define one typed, versioned response assembled by the orchestrator from the
effective provider, persisted arena state, binding/stance, budget/stop status,
target readiness and declared services. It should expose at least:

- operation name, `supported`/`ready`/`unavailable`/`unsupported` state and a
  stable reason code; resource and request limits; whether actions are recorded;
- target and foothold identities visible to this principal, plus only the
  service IDs it may forward to; no raw control-plane network details;
- HTTP/browser/PoC/file/exec/setup/forward capability where relevant to the
  caller's stance, budget remaining/deadline, binding pause, arena/system stop;
- `token_cost_hard_cap: unsupported` for external agents until trusted driver
  preflight and usage exist; provider-specific unsupported reasons rather than
  optimistic defaults.

The manifest is a bounded read. Agent views must not disclose private scenario
truth, source paths outside authorized white-box access, other bindings,
operator-only controls or credentials. MCP gets the server response rather than
reconstructing capabilities from static tool names or provider output guesses.
The console renders this response; its separate rebuild proposal does not
block adding the current Flask surface.

## Implementation order

1. **Contract and fixture.** Add ADR-0016, scenario service declaration and a
   pinned internal-only fixture. Capture the exact network/transport threat
   model and proof of reachability through the selected foothold path.
2. **Durable lease.** Add SQLAlchemy/Alembic records and DB methods for create,
   claim, connect admission, revoke, expiry and cleanup. Test PostgreSQL races:
   competing creates/stream opens, revoke versus connect, stop versus helper
   create, reset/destroy versus stale worker, and idempotency-key conflict.
3. **Provider relay.** Add a default `RangeProvider` refusal and Docker-local
   implementation with fixed destination, labels, bounded resources, verified
   cleanup and reaper recovery. A worker owns Docker operations. Prove that a
   fresh relay cannot start after the stop latch and that no helper survives a
   killed worker.
4. **REST and transport.** Add authorized lease routes and the authenticated
   byte stream/client. Direct REST must enforce the same binding, budget and
   destination checks as MCP. Close streams on revoke, expiry, pause, stop,
   arena teardown and client disconnect.
5. **Manifest and product surfaces.** Add the filtered v1 manifest, gateway
   tools and current Flask controls. Document exact limits, errors and
   unsupported providers/accounting in `docs/API.md` and gateway README.
6. **Acceptance and reconciliation.** Add a separate `make verify-nv05-live`
   isolated Compose gate with saved JSON evidence. Run `make release-check`,
   `make verify-nv05-live`, then NV-02/NV-03/NV-04 live regressions after the
   final source change. Fix failures and rerun affected gates. Record versions,
   counts, cleanup inventory and limitations in `docs/JOURNAL.md`. Only then
   accept ADR-0016 and check NV-05 in TODO/README/ROADMAP.

## Required live assertions

1. The manifest reports the Docker-local forward as ready only for the
   authorized active arena and shows truthful unsupported states elsewhere.
2. A bound attacker opens a forward to the declared internal service and an
   independent client receives the fixture's expected bytes through it.
3. Raw IP/hostname/port selection, a different target service, other segment,
   other arena, host gateway, internet and metadata endpoints are denied;
   direct REST attempts are denied as well as MCP attempts.
4. A second agent, wrong stance, revoked/paused binding and stopped arena
   cannot create or connect. Operator revoke and expiry close an already active
   stream within a measured bound. An expired lease never reconnects.
5. Race a stop with helper create and stream opening; kill the owning worker;
   restart API/gateway/worker. The latch and lease state persist, reaper cleanup
   completes without replay, and the final labeled container/network/volume
   inventory is zero. Reset and destroy also leave no live lease.
6. Console creation/revocation use CSRF and the same API; MCP discovery/control
   use the same manifest and lease state; hidden truth and secrets are absent
   from agent output, events and saved evidence.

## Reporting boundary

Planning is not implementation. Leave NV-05 unchecked until all acceptance
assertions and the pinned/PostgreSQL/live regression gates pass. Append a dated
journal entry after each material change with outcome, files, verification,
remaining risks and next step. Do not claim an SSH tunnel if the delivered
transport is a scoped TCP relay. Do not push or publish without user request.

## Fresh-session starting prompt

> Implement NV-05 in `/home/prime/Projects/Nidavellir` using
> `tmp-implementationPlan.md` as the handoff. You are the builder; do not use
> Claude or delegate implementation. Read `AGENTS.md` and its continuity sources
> in order. Start from the current local `main` HEAD (the NV-04 baseline is
> `f90d0e6`), preserve
> `docs/UI_REBUILD_PLAN.md` and the existing journal history, and keep NV-05
> unchecked until the PostgreSQL race tests, isolated NV-05 Docker live gate,
> pinned release gate and NV-02/NV-03/NV-04 live regressions pass. Build the
> scoped forward and principal-filtered capability manifest across REST, MCP
> and the current console. Record evidence and update the journal, ADR and
> roadmap status only against passing results. Do not push.
