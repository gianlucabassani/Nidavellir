# ADR-0016: Authenticated fixed-destination research forwards

- **Status:** Accepted; NV-05 acceptance gates passed 2026-09-23
- **Date:** 2026-09-23

## Context

The Docker foothold exposes command execution through Docker, not an SSH daemon.
The research workflow needs a temporary TCP connection to a declared internal
service without publishing that service on the host or granting participants
Docker control. A generic network proxy would allow lateral access beyond the
selected service.

## Decision

A scenario node may declare named `forward_services` with a TCP port. The
declaration is frozen in the NV-02 lifecycle recipe. A lease names one foothold
and one service ID; it never accepts a caller-supplied address or port. The
worker resolves both owned containers and their common arena segment immediately
before starting a relay. The relay is a trusted, labeled, resource-limited
container attached only to that segment. Its fixed program connects to the
resolved target IP and port. It has no Docker socket, credential, proxy setting,
published port or connection to the control network.

The orchestrator authenticates each lease operation and each WebSocket byte
stream with an API key header. It checks the arena binding, stance, generation,
stop gates, expiry and durable action allowance. A local client listens only on
loopback and presents the key in a header; credentials never enter a URL. MCP
and Flask manage leases through REST and expose connection instructions. They
do not carry arbitrary binary payloads as text tools.

The WebSocket API and worker exchange bounded frames over Redis keys specific
to a stream. The worker alone starts and attaches to the Docker relay. Both
sides check cancellation while pumping data. A stream has a fixed lifetime,
idle timeout and byte cap. Revoke, pause, expiry, stop and arena teardown mark
leases unusable and close live streams. Every relay carries arena and lease
labels so the reaper can reclaim it after worker loss. The API has no new Docker
operation. Creation and stream admission spend separate NV-04 actions; an open
stream is additionally bounded by bytes and time.

## Limits

Only Docker-local, one TCP service in the same declared foothold segment, and
one stream per lease are supported initially. This is a fixed-destination TCP
relay, not SSH, SOCKS, a reverse tunnel, UDP or a general network pivot.
Other provider support is reported as unsupported; only Docker-local passed a
live gate. The worker checks that the exact declared shared Docker network is
arena-owned and internal before starting a relay.
No token or monetary hard cap is claimed for external agents.

## Acceptance

PostgreSQL lease and stop races, the isolated Docker live fixture and cleanup
gate, the pinned release gate and NV-02/NV-03/NV-04 live regressions passed on
2026-09-23. See `../verification/nv05-live-2026-09-23.json` and the dated
journal. The relay uses Docker attach to the worker; Redis only transports
bounded frames between the authenticated API stream and that worker. Lease
creation spends its action atomically with the idempotent lease insert.
