# UI-R1 closure verification — 2026-10-08

This record closes UI-R1 after the React console gained the remaining operator
flows and passed focused browser checks against an isolated PostgreSQL,
Redis, Celery and Docker-local service stack.

## Operator flows

- Registered Docker-local scenario: launched a real arena from the console and
  ran a real setup command. Standard output and standard error remained
  available after setup finished and after a browser reload.
- Forward: opened a scoped service lease from the console, connected over its
  WebSocket to an internal TCP fixture, checked the echoed bytes, and revoked a
  second lease.
- Live updates: stopped the isolated orchestrator while the arena page was
  open. The event stream closed, the browser showed reconnecting, then returned
  to live updates after the service restarted and refreshed arena state.
- Lifecycle and archive: destroyed the arena from All arenas and read its setup
  output afterward. The service denied deletion of this evidence-bearing
  record. It allowed removal of an empty terminal record and clear-archive
  removed another eligible empty record while retaining the evidence-bearing
  arena.
- Custom topology: selected catalog entries and submitted them through the
  existing service contract to the mock provider. This checks the builder and
  catalog compilation path; it is not live-provider infrastructure evidence.
- Provider choices: registered-scenario launch submits the chosen provider and
  engagement intent. The UI marks Docker-local live-verified, mock simulation,
  and other providers unverified. No non-Docker provider was provisioned.

The browser run completed without page errors. Session journeys redirected an
expired signed session to login while preserving its destination, and rejected
an authenticated POST with an invalid CSRF token (HTTP 400). The detailed
runnable harnesses are `scripts/ui-r1-live-check.cjs` and
`scripts/ui-r1-safety-check.cjs`.

## Accessibility and responsive review

The scoped review used axe-core against WCAG 2.0, 2.1 and 2.2 A/AA rules on 41
page/theme combinations, including login, workspaces, forms, shared pages and
seven arena tabs in light and dark themes. The final scan reported zero
violations. Manual keyboard checks opened a destructive confirmation, kept tab
focus inside it, closed it with Escape and restored focus to its trigger. The
new launch forms and arena tabs had no page-level horizontal overflow at 320,
390, 1024 or 1440 pixels. The browser check also enabled reduced-motion
preference.

This is a documented product-team review, not a third-party conformance
certification or an assistive-technology compatibility claim. The runnable
checks are `scripts/ui-r1-accessibility-check.cjs` and
`scripts/ui-r1-keyboard-check.cjs`.

## Release verification

`make release-check` passed in the pinned Python 3.11.14 environment. Ruff and
Bandit reported no issues. The SQLite and PostgreSQL suites each reported
1,104 passed and 6 deselected. The release smoke check passed. Frontend
TypeScript/Prettier checks and the Vite production build passed.

## Remaining boundary

Docker-local is the only provider verified against real infrastructure here.
Other advertised providers remain explicitly marked unverified; their UI
selection and service request are covered, but their provisioning paths need
provider-specific live verification before anyone claims support.
