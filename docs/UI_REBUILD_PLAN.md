# Console rebuild guide

**Updated:** 2026-09-29
**Status:** Royal Command selected; ADR-0017 recorded and an opt-in React shell is
in progress at `/console`. Research now has Git, OCI and source-bundle intake,
setup steps, agent bindings, SSE-assisted state refresh, target preflight and source diff,
HTTP capture/replay, isolated browser visits, bounded foothold file transfer,
confined PoC, findings and evidence. Benchmark has a
registry, comparison creation, active-trial progress and result views. Cyber Range has a searchable
scenario library, topology preview, spec/Vulhub/model authoring, launch and
arena lifecycle views. Shared Targets, Agents, Activity, Settings
and Profile screens are present. The React source is split by feature. A dated
legacy console reference is saved. Isolated Docker-local browser journeys for
Cyber Range, source-bundle Research and scripted calibration Benchmark passed
on 2026-09-29. Route/action parity, failure-state coverage, accessibility and
usability review, the live fallback drill and the default switch remain open.
On 2026-10-07 the operator approved the console after manual review and it
became the default (`WEBUI_DEFAULT_CONSOLE` defaults to true; false restores the
legacy home). The live fallback drill passed both ways. Legacy routes remain
mounted in both settings.

## Goal and product boundaries

Build a browser-complete operator console with three primary workspaces in this order:
**Research → Benchmark → Cyber Range**. Research is the default entry after login. Use a
light theme by default, descriptive titles and actions such as **New research**,
**Run PoC**, **Record finding**, **Compare builds** and **Launch scenario**.
Keep all visible console copy in English. Remove promotional headlines, including
the current Evaluations headline, and large decorative sections.

The three workspaces share targets, agent builds, evidence, activity and settings,
plus the existing arena, gateway, event, validation and persistence services.
Docker-local is the live-supported path; mock mode is useful for UI development.
Other provider drivers are not live-verified support ([ISSUES.md](../ISSUES.md)).
This document changes no product feature or checklist status.

**Capability labels in this guide:** *Available* means a backend operation and
current console route exist, though React parity is unverified. *Partial* means
a useful slice exists but the proposed workflow or its real-world proof is incomplete.
*Planned* means the supported operation does not yet exist; show an explanation
or omit its action. Recheck labels against [TODO.md](../TODO.md),
[ROADMAP.md](../ROADMAP.md) and [ISSUES.md](../ISSUES.md) before each phase.

## Information architecture and complete journeys

Research, Benchmark and Cyber Range are the primary navigation. Shared **Targets**,
**Agents**, **Evidence**, **Activity** and **Settings** are secondary resources, with
links back to the owning work. An optional compact home view may show attention and
recent records, but does not replace the three workspaces.

| Workspace | Operator path | Result and truth boundary |
|---|---|---|
| **Research** | Import a Git object or digest-pinned OCI target; review fixed version, build inputs, configuration, seed and reset strategy; create a session; use HTTP, browser, transfer, confined PoC and agent access; inspect observations; verify and record a finding; reset or archive. | Reproducible finding with observed effect, affected identity, proof and provenance. Unknown ground truth has no invented success percentage or false-negative count. |
| **Benchmark** | Register and pin agent builds; choose versioned challenges and suite; run matched trials; inspect proof, failures and comparison; compare another build. | Separate public calibration from challenges with truth withheld from the agent. Held-out capability claims also require confirmed research material and leakage controls (NV-15). Show uncertainty and infrastructure failures separately. |
| **Cyber Range** | Select/import a scenario; inspect nodes, segments, services, roles and permissions; launch; observe state and audit; stop, reset or destroy; inspect the archived record. | Controlled environment and trace, with no evaluation score by default. Scenario and topology remain engine concepts. |

Keep challenge truth, independent validators and operator-only exports outside
agent access; participant acknowledgements do not reveal verdicts. Public
known-vulnerability fixtures and the NV-08 two-class library are **calibration**,
not held-out evidence. Research without a known solution can end inconclusively.

### Current screens and actions

These labels describe today's service/current console boundary, not the future
React screens. Each row names the screen and the action it must expose.

| Screen and action | State | Boundary or dependency |
|---|---|---|
| Research list: create, find and reopen active/archived sessions | **Available** | Existing engagements/workspace routes; migrate complete creation and review. |
| Research import: pin Git/OCI identity and review configuration | **Partial** | Intake and NV-02 manifests exist; distinguish pinned builds from mutable/manual setup. Source bundles remain a shared target option. |
| Research tools: HTTP capture/replay, browser, transfer, PoC run/cancel/result | **Available** | Existing BFF and confined helpers; unite limits, job state and evidence links. Raw TCP/UDP and runtime package install are unsupported. |
| Research findings: submit, verify, inspect evidence/change/patch | **Partial** | NV-06 validation exists; connect provenance and archived review. Non-synthetic validation remains open (NV06-R1). |
| Research affected/fixed replay, fuzzing, campaigns/disclosure | **Planned** | NV-11, NV-12 and NV-14; no enabled controls before acceptance. |
| Benchmark: register build/challenge/suite and launch paired trials | **Available** | NV-07 records/current Evaluations forms; label scripted driver and calibration scope. |
| Benchmark: inspect trials, proof, uncertainty, failures and comparison | **Partial** | NV-07/08 results exist; durable model-driven suite remains unproven (NV07-R1). |
| Benchmark: held-out challenge and active episode | **Planned** | NV-15 requires confirmed research, private truth and leakage policy. |
| Cyber Range: scenario/topology, launch, events, stop, reset, archive | **Available** | Existing scenario, arena and lifecycle routes; surface roles and exact resource state. |
| Cyber Range: live VM/cloud or multi-agent red/blue | **Planned** | Docker-local alone has the live gate; other provider/multi-agent breadth deferred. |
| Shared targets, agents, evidence, audit, model connection/settings | **Partial** | Current indexes and controls vary; inventory real actions before defining registry editing. |

## UI rules and component contracts

Design the three workspace flows end to end before polishing secondary pages.
Produce two reviewable concepts for the same Research task: import, PoC, finding
and archived evidence. Select one with researcher feedback, then apply its
small design system to Benchmark and Cyber Range. Default to an accessible
light theme; test a dark option before shipping it.

Keep target identity, arena state, stance, time and remaining action budget in
context. Titles describe record/state (“Research on <target>”, “Build comparison”,
“Scenario topology”). Primary actions name their effect. Avoid a hero, slogan
or ornamental KPI strip; counts link to records.

Define components for dense sortable/filterable tables; code and PoC editing;
bounded stdout/stderr and event logs; HTTP and Git diffs; node/segment topology;
protected evidence with digest/provenance; verdict/uncertainty badges; and
confirmation dialogs naming the exact target/consequence. Long hashes, code
and logs scroll within their regions. Keyboard navigation, focus, semantic
labels and reflow belong in every component contract.

Design loading, empty, validation error, permission denial, expired session,
disconnected/stale stream, failed operation, unsupported capability and
archived/read-only states for every data-heavy view. Preserve valid form input
after errors. Mark last observed state and refresh time; cached browser state
never authorizes lifecycle, budget, stop or scoring. The PoC editor shows target,
files, limits, run/cancel/cleanup, output and artifact links. Do not persist
sensitive drafts in browser storage by default. Archived evidence remains
readable after teardown.

## Architecture decision and migration

Before React implementation, write a **new ADR** that supersedes **only** the
Flask/Jinja rendering and tooling choice in
[ADR-0012](adr/0012-gui-first-product-model.md). Preserve its GUI-first product
model, shared objects, thin console, staged parity and service authority.
Explain the benefit of React/TypeScript/Vite and the build, rollback and security
costs. Do not reinterpret ADR-0012 as approval for a frontend rewrite.

Build `cyber-range/webui/frontend/` with React, TypeScript and Vite. Flask stays
the same-origin web backend: it serves the built shell/assets, owns session
login, CSRF, uploads/downloads and SSE proxying, and keeps orchestrator keys
on the server. The browser uses one typed BFF client. Add narrow JSON
projections where Jinja alone assembles page data. Authorization, policy,
lifecycle, validation, scoring and provider work stay in existing services;
preserve independent API/MCP use. Pin Node/dependencies, self-host assets and
reproduce the build in CI.

The typed client handles 401/session expiry, CSRF, validation errors, aborts,
idempotent retries and protected downloads. URLs own shareable tabs/filters;
local state owns short-lived drafts/dialogs. Use one event stream per live
record with event-ID resume and a fresh fetch after reconnect; bound polling
fallback. Keep API keys, encryption keys and agent credentials out of bundle,
bootstrap HTML, URLs and browser storage. Escape target/job output, retain
audit attribution and review new BFF routes for access and upload bounds.

Migrate one **complete path** at a time behind a route/feature switch. Keep
old Flask pages and deep links until replacements cover their actions and
states. Translate `/arena/<id>` and fragment tabs, `/launch`, `/wizard`,
`/engagements`, `/evaluations` and resource bookmarks only after tested
parity. Before the default switch, save the current Jinja templates, CSS,
JavaScript and representative desktop/mobile captures in a dated
`docs/assets/legacy-console-reference/` backup with a file manifest, so its
useful visual details remain available. Keep a tested switch back through
cutover; retire old assets later.

The first backup is at
[2026-09-28/MANIFEST.md](assets/legacy-console-reference/2026-09-28/MANIFEST.md).
Refresh it if the legacy visual design changes before cutover.

## Delivery sequence

| Phase | Screens and contracts | Completion criterion |
|---|---|---|
| **0. Inventory** | Route/action/role/state matrix for Flask pages, BFF and JS; desktop/phone captures, task observation, baseline timings. | Each current operation has owner, endpoint, destination, deep-link rule and status; three journeys and two Research concepts reviewed. |
| **1. Concept/design system** | Chosen concept; shell/navigation; tokens, typography, forms, tables, logs, code, diff, topology, evidence/states and responsive gallery. New ADR and typed BFF map. | All three journeys clickable; gallery passes initial keyboard/reflow review; ADR recorded before build. |
| **2. Shell/Research** | Same-origin login; Research list/import/pin/create; overview/live/tools/PoC/findings/evidence/archive. Manifest, job, verdict, protected-file and SSE contracts. | Docker-local human creates pinned session, runs tools/PoC, records finding, resets and reviews evidence after teardown without legacy page. |
| **3. Benchmark** | Build/challenge/suite forms, launch, trial/evidence detail, comparison/failure states. NV-07/08 records, calibration, interval and operator-only contracts. | Two pinned scripted builds run matched calibration trials; result explains effects, uncertainty and infrastructure failures. Stronger claims stay labelled by evidence. |
| **4. Cyber Range** | Scenario catalog/preview, topology/roles, launch, live observation, stop/reset/destroy, archive. Schema, capability, provider-state and event contracts. | Docker-local topology launches, reconnects, stops/resets and archives with permissions/trace; unsupported providers explicit. |
| **5. Shared work** | Targets, agents, evidence, activity/audit, settings/profile, cross-links, old route aliases. | Every old action has a working destination or documented planned state; bookmarks resolve. |
| **6. Verification/switch** | Parity, browser, accessibility/security, performance, release/live gates and fallback drill. | Gates below pass with dated artifacts; new UI becomes default, old routes remain until later retirement. |

NV-09 Bughunt integration is separate. NV-11 replay, NV-12 fuzzing, NV-14
campaign/disclosure and NV-15 held-out work get UI controls only when their
service contracts and evidence land. NV-13 local VM intake needs a selected
target and live lifecycle proof.

## Parity and verification contract

Phase 0 records one row per old route **and** action: old URL/method/role/CSRF,
result states, new URL, BFF contract, deep link, test and decision. Expand
these groups to actual endpoints in `cyber-range/webui/app.py` and browser JS.

| Existing flow | Required parity |
|---|---|
| `/login`, `/logout`, `/`, `/engagements`, `/engagements/new`, `/launch`, `/wizard` | Login/logout, creation modes, invalid input, session expiry, bookmarks. |
| `/arena/<id>`, setup, bindings, stop/resume, `/reset/<id>`, destroy/archive | Tabs/fragments, roles/stop, replacement reset, live/archive and evidence. |
| Arena `/api` HTTP, browser, transfer, PoC and finding endpoints | Replay, file bounds, submit/cancel/result, digest, verdict, denial. |
| `/evaluations`, detail, build/challenge/suite/create | Build identity, matched seeds, proof, comparison/calibration labels, infrastructure failures. |
| `/scenarios`, `/library/*`, `/activity/*`, `/agents`, `/settings`, `/profile` | Resource links, topology, audit, downloads, controls/foundation states. |
| `/api/arenas/<id>/stream` | SSE event-ID resume, stale marker, reconnect reconciliation, archive. |

Future browser scenarios cover Git/OCI or fixture creation, research/HTTP
replay, PoC submit/cancel, finding/verdict, reset, paired build comparison,
SSE interruption/reconnect, session expiry during mutation, and evidence
after teardown. Exercise role denial, CSRF, mock and Docker-local. Use
component/contract tests for data/error boundaries and browser tests for
complete tasks. Capture screenshots and dated results.

Target WCAG 2.2 AA with automated checks plus manual keyboard, focus, screen
reader and zoom/reflow review. Check 1440, 1024, 390 and 320 px widths,
including tables, code, topology and dialogs. Observe at least three
representative researchers completing the three workspace tasks; resolve
blockers and repeat failures. Set performance budgets from phase-0 baseline
on the same stack/browser. Review built assets/BFF for secrets, XSS,
cross-origin dependencies, CSRF, downloads and audit attribution.

Before default switch, run pinned `make release-check` and relevant Docker-local
lifecycle/PoC/evaluation live gates, then the fallback drill. Record versions,
pass/skip counts, browser scenarios, accessibility findings and unresolved
risks in a dated verification artifact. Existing NV-01–08/NV-10 gates are
**backend evidence**, not React parity/usability/cutover evidence. Keep
NV06-R1, NV07-R1 and INFRA-R1 open until their closing evidence exists.

## First implementation ticket

Inventory route/action parity and produce two clickable Research concepts
showing immutable import review, PoC, finding/evidence attachment and archived
inspection. Use the review to settle the new ADR, BFF contracts and measurable
acceptance budgets before building the shell.
