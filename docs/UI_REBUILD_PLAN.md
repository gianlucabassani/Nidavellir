# Console rebuild plan

**Prepared:** 2026-09-23  
**Status:** Proposed; planning only. No UI implementation or roadmap task is complete by this document.

## Objective

Replace the Flask/Jinja-rendered operator interface with a newly designed,
maintainable browser application that a human researcher can use from engagement
creation through reproducible evidence and teardown. Preserve the shipped
orchestrator, worker, MCP gateway, records, security boundaries, and their API
behavior. The new interface must be more legible and comfortable for sustained
research, while remaining honest about capabilities that are still planned.

This is a frontend remake, not a rewrite of arena execution, scoring, database
models, or agent policy. Backend changes are limited to the presentation/BFF
contract needed to expose existing data and actions cleanly.

## Starting point and decision to change

The current console has roughly 2,000 lines of Flask routes, 2,700 lines of
browser JavaScript, 870 lines of CSS, and many Jinja templates. Its C1–C4
navigation and contextual workspace are shipped. NV-03 added a working PoC tab,
but the new tab has not had the same task-based visual/usability review as the
earlier shell and workspace. Evaluations, target and agent registries, and some
administration destinations are honest foundations, not finished product flows.

ADR-0012 explicitly retains Flask/Jinja rendering and rejects an immediate SPA.
Before implementation, record a **new proposed ADR** that supersedes only that
rendering/tooling choice, explains the measured benefit of a fresh frontend, and
retains its GUI-first product model, thin console, staged parity, and API-backed
authority. Do not silently reinterpret the old ADR as approval for a rewrite.

## Target product experience

One coherent application shell: Home, Engagements, Evaluations, Library,
Activity, and Administration. An engagement is the main research workspace.
Keep task context visible: target identity, arena state, remaining time, selected
stance, access limits, and the primary safe next action. Show only applicable
panels, and clearly distinguish live state from the last recorded state.

The visual direction should be selected through two reviewed concepts, then
implemented as a small design system. Keep Nidavellir's identity but revisit
typography, spacing, color, iconography, hierarchy, density, and responsive
behavior. Prefer clear evidence and state over decorative dashboard chrome.
Support long text, logs, hashes, diffs, topology, and code without forcing
horizontal page scrolling. Make dark and light themes legible; if a second
theme is deferred, the primary theme must still meet accessibility targets.

### Page and workflow inventory

| Surface | Rebuild scope and completion condition |
|---|---|
| Login and shell | Same-origin session login/logout, health/offline state, navigation, global Create, breadcrumbs, keyboard access, responsive layout. |
| Home | Live engagements, attention, findings awaiting review, capacity/health and recent activity; each count opens its underlying record. |
| Engagements | Active/archive search and filters, state/expiry, destroy/reset with reviewed confirmation, retained record after teardown. |
| New engagement | One guided flow for challenge, generated/imported scenario, Git, OCI and bundle targets; purpose, participant, time box, setup consent, immutable review, launch and resumable error states. |
| Workspace overview/live/target | Readiness, topology, setup/configurator, lifecycle, live events and target identity; restore view after refresh or stream reconnect. |
| Research tools | HTTP compose/inspect/replay/attach; browser validation; transfer files; code editor for confined PoC, target/limits, run/cancel, output, artifact metadata and prior jobs. |
| Findings/evidence/changes | Author, link proof, confirm/refute, browse protected artifacts and diffs, inspect provenance and archived results. |
| Agent/trace/score/infrastructure | Authorize/pause/revoke, connection recipe, event trace, score where applicable, resource inventory; no scoring language in manual-discovery views. |
| Activity | Global findings, evidence, agent activity and audit with filters, deep links and explicit unavailable/pruned states. |
| Library/settings/profile | Current challenge/catalog and model/settings workflows, plus clearly labelled foundation screens for backend registries or controls that do not exist yet. |
| Evaluations | Honest foundation until NV-07 supplies durable records; design the route and component contract without fabricating runs, comparisons or controls. |
| Legacy links | Preserve `/arena/<id>`, `/launch`, `/wizard`, and other public bookmarks until canonical replacements and deep-link translation pass. |

### Researcher usability requirements

- A human can complete three uninterrupted journeys in the browser: create a
  manual research engagement and produce a finding; connect/pause/review an
  attacker agent; reset or archive an engagement and inspect retained evidence.
- The PoC tool offers a usable code editor, example/template, target and file
  selection, clear limits, visible execution/cleanup status, readable stdout and
  stderr, artifact inspection, and a link into finding creation. Draft handling
  must avoid leaving sensitive source in persistent browser storage by default.
- Distinguish authoritative result from operator notes, protected evidence from
  convenience output, and available action from a future capability.
- Forms preserve valid input after validation errors. Destructive or egress
  changing actions show the exact target and consequence before confirmation.
- Loading, empty, stale, offline, failed and archived states are designed for
  every data-heavy view, rather than left to generic alerts or blank panels.

## Proposed implementation architecture

1. Create `cyber-range/webui/frontend/` as a new React + TypeScript application
   built with Vite. Use route modules for page boundaries and small components
   for the shell, data tables, forms, status, evidence viewers, code and topology.
   React's existing-project guidance and Vite's backend-integration guide cover
   this deployment pattern: [React](https://react.dev/learn/add-react-to-an-existing-project),
   [Vite](https://vite.dev/guide/backend-integration).
2. Keep Flask as the same-origin browser-facing backend during migration. It
   serves the built asset manifest and shell, retains session login, CSRF checks,
   uploads, downloads and SSE proxying, and keeps the orchestrator API key on the
   server. The browser talks only to the existing `/api` BFF surface. Add narrow
   JSON projections for page data currently assembled only for Jinja; do not
   move policy, scoring, orchestration or provider operations into React.
3. Use typed request/response contracts and one fetch layer for credentials,
   CSRF, validation errors, 401/session expiry, aborts and retries. Choose a
   single route/data strategy during the architecture spike; React Router's
   documented modes support the needed nested URL structure
   ([official modes](https://reactrouter.com/start/modes)). Do not maintain two
   competing caches. URL paths and query parameters own shareable tab/filter
   state; component state owns short-lived editor and dialog state.
4. Keep one SSE connection per open engagement, resume from event IDs, reconcile
   after reconnect, and fall back to bounded polling only when necessary. Mark
   stale data visibly. Never make browser-side timing or cached state the
   authority for stop, cancellation, budgets, permissions or lifecycle.
5. Build the frontend in a pinned Node image; ship static assets in the existing
   WebUI container. Pin dependency versions and lockfile, audit the supply chain,
   self-host required fonts/icons/assets, and retain a reproducible build in CI.
   No public CDN should be required to render the operator interface.

The API key, encryption keys and agent credentials must never enter the bundle,
HTML bootstrap data or browser storage. Escape untrusted target content and job
output by default. Preserve CSRF on mutations, protected artifact downloads,
same-origin session handling, bounded uploads and confirmations. Require a
security review of the new bundle and BFF routes before cutover.

## Delivery sequence and gates

| Phase | Work | Exit gate |
|---|---|---|
| 0. Baseline and research | Inventory every route/action/role/state; capture current desktop/phone screenshots and interaction recordings; observe the three researcher journeys; list pain points and measure baseline load/interaction times. | Approved parity matrix, task findings, and two visual concepts. |
| 1. Architecture and contracts | Proposed ADR, route map, BFF JSON contracts, auth/CSRF/SSE prototype, pinned frontend toolchain and build integration. | New shell can log in, load one real engagement, reconnect to events and pass auth/CSRF tests beside the old UI. |
| 2. Design system | Tokens, typography, color, spacing, layout, icons, forms, tables, tabs, dialogs, notifications, empty/error states, code/log/evidence viewers; responsive and keyboard behavior. | Reviewed component gallery at desktop/tablet/phone sizes, with accessibility checks. |
| 3. Core journey | Home, engagement list/archive, unified creation, workspace overview/live/target and lifecycle. | A real Docker-local target can be created, inspected, reset and archived in the new UI. |
| 4. Research journey | HTTP/browser/transfer, PoC, findings/evidence/changes, agent/trace/score/infrastructure. | A human completes the full discovery and agent journeys with retained proof and no legacy page. |
| 5. Long tail and parity | Activity indexes, challenge library, settings/profile, honest foundation screens, aliases/deep links and uncommon error/permission states. | Every supported old action has a new destination or an intentional, documented replacement. |
| 6. Hardening and cutover | Live visual/usability review, accessibility/security/performance audit, regression gates, staged default switch and fallback drill. | New UI becomes default only after the acceptance gates below pass; remove old templates/JS/CSS in a later cleanup change. |

Implement phases behind a route or feature flag so the old console remains
operable during construction. Migrate by complete journey, not isolated screens.
Keep a tested rollback path until archived records, upload/download, reset,
PoC cancellation and session expiry work in the new interface. Retire legacy
routes and assets only after deep-link and parity checks.

## Acceptance and verification

The rebuild is complete only when all of the following are recorded with
screenshots, test output and a dated verification artifact:

1. The parity matrix covers all current routes and actions, including CSRF,
   permission denial, mock mode, Docker-local mode, archived records and
   currently planned/foundation destinations. No working action disappears.
2. Automated component/contract tests and Playwright end-to-end journeys cover
   login, creation, reset, HTTP/replay, transfer, PoC submit/cancel/result,
   finding/verdict, agent pause/revoke, SSE reconnect and retained evidence.
   Re-run `make release-check`, `make verify-nv02-live` and
   `make verify-nv03-live` after the cutover. Playwright supports browser and
   accessibility checks ([official guide](https://playwright.dev/docs/accessibility-testing)).
3. Target WCAG 2.2 AA, with automated checks plus manual keyboard, focus,
   screen-reader and zoom/reflow review; automated checks alone are insufficient
   ([W3C standard](https://www.w3.org/TR/WCAG22/)). Verify at 1440px, 1024px,
   390px and 320px widths, with no lost action or unintended page overflow.
4. Run moderated or observed task sessions with at least three representative
   human researchers. Record completion, errors, hesitation and qualitative
   feedback; resolve all critical blockers and repeat the failed tasks. This
   gates the claim that the UI is comfortable, which code tests cannot prove.
5. Compare load and interaction measurements with the baseline on the same
   pinned local stack and browser. Set numerical budgets from that baseline in
   phase 0; do not declare the new UI faster from screenshots alone.
6. Verify no API key/secret in client assets, no new cross-origin dependency,
   no unescaped target/job output, no mutation without CSRF, and no loss of
   audit attribution. Confirm the fallback switch restores the old UI without
   touching arena or evidence records.

## Scope control and dependencies

This rebuild may proceed alongside NV-04/NV-05 only with a shared API contract
and an integration owner. NV-04 budgets/stop and NV-05 scoped access should
define their UI states before their controls are wired into the new workspace.
NV-07 evaluation screens remain foundations until the durable experiment model
exists. Do not count styling a planned feature as implementing it.

The estimate should be finalized after phase 0. For planning capacity, assume
roughly **12–20 engineer-weeks** for the shipped console parity and cutover,
plus design/research and part-time backend review; this is an inference from the
current route/workflow inventory, not a delivery commitment. Parallel work can
shorten elapsed time, but auth, contracts, design system and cutover are serial
gates. The main risks are hidden behavior in the monolithic Flask/JS code,
fragmented backend projections, SSE/session edge cases and regressions in rare
research workflows.

## First implementation ticket

Produce the phase-0 parity matrix and two clickable visual concepts for a
manual-discovery workspace, including a PoC run, evidence attachment and
archived result. Review those with a researcher and use the outcome to finalize
the proposed ADR and acceptance budgets before building the new shell.
