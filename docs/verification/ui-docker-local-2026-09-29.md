# Royal Command Docker-local Cyber Range journey — 2026-09-29

**Stack:** isolated `docker-compose.nv02.yml` project with PostgreSQL 16,
Redis, orchestrator, worker and the packaged React WebUI at port 15000;
`MOCK_MODE=false`, `RANGE_PROVIDER=docker-local`. The existing mock development
stack was not modified. The fixture was the local content-addressed NV-02
reset image, with HTTP readiness on `/state`.

## Browser journey

Chromium used the new React console to import a v3 scenario after preview and
launch a Docker-local arena. In the final replay the service assigned original arena
`4df77829-c34c-446c-b724-538c134c7df3`; its BFF state reached `active` and
the React arena view showed a running target. The browser sent `GET /state`
through the HTTP workbench, received 200 and a stored transaction, followed
its digest into the Findings form and recorded an operational observation.

The browser requested a recipe reset. The replacement
`570872a4-c935-4461-8e31-8c41613ae86a` became active, while the original
became `destroyed` and its finding remained readable in the React Findings
view. The browser destroyed the replacement through its confirmation dialog,
then deleted the imported fixture pack from the scenario library. Docker
reported zero containers and networks carrying either arena label. The
isolated Compose project, volumes and network were removed; `compose ps` is
empty. The live [arena render](../assets/ui-concepts/renders/royal-command-docker-local-arena.png)
was inspected.

## Defect found and fixed

The first visit to the HTTP tab after a transaction existed crashed React.
The service's list endpoint returns small transaction **manifests**, while
the UI had treated each list item as a full request/response envelope. The
ledger now renders manifest fields and loads the envelope only on Inspect or
Replay. The rerun showed both the prior manifest and the new transaction,
displayed its request/response details and linked its digest to a finding.
The TypeScript contract now separates `HttpTransactionManifest` from the full
`HttpTransaction` envelope. `npm run check` and the production build passed
after the fix; the isolated packaged WebUI image rebuilt successfully.

The first live arena render also showed a future expiry before the displayed
observation time. Database datetimes are naive UTC strings, while observation
timestamps carry an offset. The shared formatter now treats only naive
datetime values as UTC. The final live render showed observation at 9:47 AM
and the one-hour expiry at 10:47 AM in the same local time zone. The final
replay completed the full journey after this frontend-only correction.

## Limits

This is one local Cyber Range fixture and an operator observation, not an
independently validated vulnerability. It does not close UI-R1: full Research
and Benchmark browser journeys, Browser/Transfer helper execution, all legacy
action/deep-link parity, accessibility/usability review and fallback drill
remain. The pinned Python `make release-check` passed earlier in this work
after the evaluation projection change; the subsequent HTTP and time fixes changed only
frontend code and passed its TypeScript, formatting, production and packaged
build checks.
