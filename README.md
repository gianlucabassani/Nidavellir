# Nidavellir

Nidavellir is a self-hosted workspace for authorized security research and
testing security agents. It starts reproducible targets in Docker, gives a
human or an agent a scoped place to work, records evidence, and checks findings
against the target. You bring the agent; Nidavellir does not run an autonomous
pentester for you.

The same tools also support controlled agent comparisons. Public and synthetic
challenges are calibration material, not proof that an agent can find unknown
vulnerabilities.

## What you can do

- Import a Git repository, container image, or source bundle and record the
  version under test.
- Launch a local arena and work through the browser, HTTP, file-transfer, and
  confined proof-of-concept tools.
- Connect a compatible agent through the scoped MCP gateway.
- Keep findings, traces, and evidence available after an arena is removed.
- Compare pinned agent builds on repeatable challenges.

Docker-local is the only infrastructure provider verified with live runs.
Other provider options are marked unverified until their own live checks pass.

## Run the development stack

You need Docker with Compose. From the repository root, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Open the console at <http://localhost:5000>. The local development login is
`admin` / `nidavellir`; these defaults are for a machine you control and must
not be exposed as production credentials. The API is at
<http://localhost:8000>. The development stack uses mock mode, so it does not
start real target infrastructure.

The React console is the default. To open the legacy home, use
<http://localhost:5000/?legacy=1>. To stop the stack, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

For real Docker-local arenas, configuration, and data handling, see
[Operations](docs/OPERATIONS.md). Do not expose the development stack to the
internet.

## How it is put together

```text
Browser console ── Flask session/BFF ── FastAPI services ── Celery workers
        │                                    │                    │
        └── scoped MCP gateway                └── PostgreSQL      └── providers
```

The browser talks to Flask, which handles login, sessions, CSRF, and protected
files. Services own authorization, arena lifecycle, validation, and scoring.
Workers manage target infrastructure. PostgreSQL stores records and an
append-only event history. Agents use the same bounded services through MCP.

## Project status

The core Docker-local research flow and the console cutover are complete. The
console can launch and review work, show setup output, build custom topologies,
and select providers with clear verification labels. UI-R1 was closed on
2026-10-08; its live and accessibility checks are recorded in
[the closure report](docs/verification/ui-r1-closure-2026-10-08.md).

The research-quality follow-up repaired probe controls, complete source inventories
and failed-query auditing. [Its verification report](docs/verification/research-quality-closure-2026-10-12.md)
records the exact limits; source candidates still require human semantic review.
[UI-R2](docs/verification/ui-r2-closure-2026-10-16.md) brings actor requests,
prerequisite controls, effects and evidence together in the console, including
post-teardown review. [Request comparison and source candidate browsing](docs/research/research-usability-next.md)
remain later slices.
Cloud and other VM providers, multi-tenant hosting, and multi-agent red/blue
work remain deferred. The ordered checklist is in [TODO.md](TODO.md); product
scope and design detail are in [ROADMAP.md](ROADMAP.md); current risks are in
[ISSUES.md](ISSUES.md).

## Documentation

- [Operations](docs/OPERATIONS.md) — local setup and running the platform
- [API](docs/API.md) — service endpoints and data contracts
- [Scenarios](docs/SCENARIOS.md) — target and topology format
- [Security](docs/SECURITY.md) — trust boundaries and containment
- [Architecture decisions](docs/adr/README.md)
- [Research journal](docs/JOURNAL.md) — dated changes and verification

The interactive documentation site is available at
<https://gianlucabassani.github.io/Nidavellir>.

## License

MIT.
