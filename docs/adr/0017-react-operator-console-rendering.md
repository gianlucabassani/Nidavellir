# ADR-0017: React rendering for the operator console

- **Status:** Accepted — default cutover approved 2026-10-07; verification follow-ups open
- **Date:** 2026-09-27
- **Deciders:** Nidavellir operator
- **Supersedes:** ADR-0012 section 5's Flask/Jinja rendering and no-build-tool choice only

## Context

ADR-0012 established a browser-complete, GUI-first product model with a thin
console and API-owned orchestration. Its Flask/Jinja rendering choice served the
first grouped navigation, but the Research, Benchmark and Cyber Range journeys
now need one contextual workspace with live jobs, evidence, comparison and
lifecycle states. The current page scripts and templates repeat state and
navigation logic. The approved Royal Command direction also needs consistent
responsive components and a tested light/dark theme.

## Decision

Use React, TypeScript and Vite in `cyber-range/webui/frontend/` for the new
operator surface. Flask remains the same-origin web backend. It owns login,
session cookies, CSRF, uploads, protected downloads and event-stream proxying;
it serves a versioned built shell and static assets. The browser calls only a
typed Flask BFF client. Orchestrator credentials never enter HTML, the bundle,
URLs or browser storage. Flask BFF routes expose narrow, authorized projections
where current Jinja pages assemble several API responses.

The new UI has three primary workspaces: Research, Benchmark and Cyber Range.
Shared Targets, Agents, Evidence, Activity and Settings are secondary routes.
Royal Command is the selected visual system: light by default, with an optional
royal dark theme, a centered angular top navigation and restrained rune marks
for the three workspaces. Theme preference may be stored locally; research
drafts, keys and authorization state may not.

Migrate complete operator paths behind a route switch. Preserve existing Flask
pages and deep links until each replacement covers actions, errors and read-only
states. The switch back remains tested through cutover. React never decides
authorization, budgets, lifecycle transitions, validation or scoring from cached
state; the existing services remain authoritative. Independent API/MCP clients
continue to work without the browser.

## Consequences

- Reusable typed components can cover dense tables, topology, bounded logs,
  evidence, forms and dialogs across the three journeys.
- A Node dependency tree, pinned lockfile, reproducible asset build and CI gate
  become release requirements. Built assets must be self-hosted and versioned.
- Client routing, CSRF, 401 expiry, aborts, idempotent retries, SSE reconnect and
  fresh reconciliation need explicit contracts and tests.
- Keeping both renderers during migration costs route and template maintenance.
  The parity matrix governs when a legacy page may retire.
- New BFF projections require access-control, output-escaping, upload-bound and
  protected-download review. React text rendering is the default; raw HTML from
  target/job content is forbidden.

## Preserved ADR-0012 decisions

The GUI-first product model, explicit Target/Scenario/Challenge/Agent build/
Engagement/Evaluation/Run/Arena/Evidence objects, contextual workspace, thin
console, staged parity and service-owned business rules remain in force. This
ADR changes rendering and frontend tooling only.

## Alternatives

- Continue growing the Jinja page scripts: this leaves live workspaces and
  reusable state handling fragmented across pages.
- Replace Flask with a browser-to-orchestrator client: this would expose a new
  credential and authorization boundary and complicate protected files and CSRF.
- Switch every route at once: this would retire working deep links before parity
  is demonstrated.

## Default cutover and verification boundary

The operator approved Releases G–H after manual review ("Overall approved"),
and the default changed to `/console` on 2026-10-07. The pinned release gate,
legacy fallback drill and browser checks at 320–1440 px are recorded. See
[cutover evidence](../verification/ui-default-cutover-2026-10-07.md).

Two verification items from the original pre-cutover checklist remain open:

- Record the session-expiry, CSRF-denial and reconnect browser journeys in
  `docs/verification/`.
- Record a formal accessibility review, including keyboard use and reflow.

UI-R1 remains open for these items, remaining route/action parity and live
service verification. The approved default switch does not establish full
UI parity or feature completion. `WEBUI_DEFAULT_CONSOLE=false` restores the
legacy home, `/?legacy=1` reaches it while the console is default, and legacy
routes remain mounted.
