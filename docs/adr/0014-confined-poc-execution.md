# ADR-0014: Worker-owned networkless PoC execution with fixed-target relays

- **Status:** Accepted (2026-09-22)
- **Date:** 2026-09-22
- **Deciders:** Gianluca Bassani

## Context

Nidavellir needs to execute researcher-authored Python against an arena without
turning that source into a general network client or giving it access to the
Docker control plane. Attaching an untrusted helper to an arena bridge is not a
selected-target boundary: it also exposes peer nodes, bridge gateways and any
route the arena happens to have. Python language restrictions are not a security
boundary, and Celery delivery or process cleanup alone is not durable ownership.

## Decision

The API stores an immutable, content-addressed PoC job and reserves nullable
unique database leases for arena and global admission. An idempotency key is
bound to source/file bytes, selected target, runner image and limits. The worker
alone claims the job and creates helpers. Claims, deadlines, cancellation,
terminal outcome and verified cleanup are durable and separate. A stale running
claim is failed and reconciled by stable labels; it is never replayed because a
lost process may already have changed the target.

The operator prebuilds a trusted Python 3.11 image. Execution never pulls or
builds a participant image. The source runner is non-root, read-only except for
bounded tmpfs, capability-free, `no-new-privileges`, default-seccomp confined,
PID/CPU/RAM/time limited, and has Docker `network_mode=none`. It receives no
socket, device, host mount, credential or proxy environment. Input is copied
through the Docker API into fixed paths and stdout, stderr, daemon logs and
regular-file artifacts are bounded during production or collection.

Optional target access is HTTP(S) only. A trusted relay joins the selected
target's owned arena segment and exposes a job-owned Unix socket in a private
volume. The untrusted runner can request only relative paths; the relay always
connects to the worker-resolved target IP and port, does not follow redirects,
and does not provide CONNECT, DNS or arbitrary upstream selection. Raw TCP/UDP,
runtime package installation and caller-selected images remain unsupported.

Browser helpers use the same fixed-target idea: Chromium joins a disposable
internal helper network and is configured to use a trusted, dual-homed proxy
that accepts only the selected target IP/port. The proxy rejects off-target
redirects and subresources. The existing single HTTP transaction helper never
follows redirects. All helper resources carry stable arena/role labels and are
removed and verified by their owning operation or arena cleanup.

HTTP/browser API requests (including the browser validation oracle) enqueue the
same durable job machinery and wait for a bounded result, retaining their REST
contracts. Workers recheck the arena and agent binding before execution. Helper
networks also carry the job label, allowing recovery after a worker dies.

Admission serializes with the arena state transition. Teardown cancels queued
work and drains claimed jobs before removing the arena inventory. Failed cleanup
remains a reaper obligation and retains admission slots until verified. Expired
queued work is cancelled without execution. Cancel-versus-claim uses conditional
database writes, and idempotency also binds the submitting principal.

REST, console and attacker MCP entry points share `CAP_EXEC`, arena/binding
checks and body-free audit metadata. Agent reads and cancellation are limited to
their own jobs; operators can retain results after arena teardown. Source and
results use the existing protected-secret storage convention.

## Consequences

- A useful Python PoC can reach one declared arena web service without gaining
  an IP route to the host, control plane, peers, other arenas, internet or cloud
  metadata.
- Redirects are returned as data to Python rather than followed. Browser
  redirects/subresources are mediated by the fixed proxy.
- Docker-local is the only supported backend. Other providers fail explicitly
  until they can demonstrate equivalent isolation and cleanup.
- Containers still share the host kernel. This is defense in depth for trusted
  local research hosts, not a VM-grade hostile multi-tenant sandbox. Kernel and
  Docker-daemon patching remain operator responsibilities.
- The worker retains root-equivalent Docker socket authority; participants and
  their source never receive it. Moving that authority behind a narrower remote
  execution service remains a future hardening option.
