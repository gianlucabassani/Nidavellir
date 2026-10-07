# Development journal

Dated handoffs record changes and actual verification. TODO.md is the canonical ordered
work queue; ROADMAP.md retains design detail and historical milestone mapping.

## 2026-10-07 — Prepare Royal Command merge and fix focused review findings

**Outcome:** Committed the previously uncommitted work as three phase commits:
Release G (`94cfb4e`), Release H (`dc93f04`) and approved default cutover
(`95b03f4`). ADR-0017 now records the operator-approved 2026-10-07 default
switch and explicitly retains the unrecorded security/reconnect browser journeys
and formal accessibility review as open items. Independent Standards and Spec
reviews found four unique P2 defects in the new BFF/trace/forward paths; all were
fixed and re-reviewed with no remaining blocker in that focused scope. Trace
now uses the actual export keys and type-filtered event presence queries.
Forward reads fail visibly; retries preserve a browser action key and reuse the
service's existing idempotency/budget contract. UI-R1 remains open.

**Files:** `cyber-range/webui/app.py`, `frontend/src/arena/record.tsx`,
`tests/test_webui.py`, `scripts/ui-forward-retry-check.cjs`, ADR-0017,
`ISSUES.md`, cutover evidence and
`docs/verification/ui-merge-review-2026-10-07.md`, plus this journal.

**Verification:** Regressions failed before fixes and passed afterwards; full
WebUI tests passed in pinned Python 3.11. Browser retry regression passed with
all API calls intercepted; Release H smoke passed 25/25 with mutations refused.
TypeScript, Prettier and Vite passed. Final corrected `make release-check` passed
on Python 3.11.14: Ruff clean, Bandit zero medium/high findings, SQLite 980 passed
(4 skipped, 6 deselected), PostgreSQL 984 passed (6 deselected), migration and
API/UI/gateway readiness smoke. `git diff --check` passed.

**Unresolved risks / next concrete step:** Publish the review-fix commit and open
the PR against `main`; check remote CI before merge. The focused review does not
claim exhaustive review of the entire console branch. Complete UI-R1 separately:
legacy-only setup output/custom topology/non-Docker launches, real-service
forward/archive/list-destroy journeys, session expiry/CSRF denial/reconnect and
formal accessibility evidence. The mock review arena and rejected reference
artifacts remain untouched.

## 2026-10-07 — Royal Command console becomes the default UI

**Outcome:** The operator reviewed Releases G–H and approved them ("Overall approved"). `WEBUI_DEFAULT_CONSOLE` now defaults to true in `app.py` and `docker-compose.yml`, so `/` (and the post-login landing page) opens `/console`. Setting it to false restores the legacy home. The console footer's "Legacy console" link uses `/?legacy=1`, which bypasses the redirect so the legacy home stays reachable. Follow-up fixes:
- **Research layout:** the cards are now two independent columns (01/03/05 and 02/04/06), so right-hand cards no longer leave gaps waiting on taller left-hand cards; one-column order is preserved with `order`.
- **Topology draw-in:** it now uses a fixed long dash. With `pathLength`-relative dashes the edges could stay dotted.

**Incident:** during the first fallback drill the WebUI container was recreated with plain `docker compose up -d webui`. That dropped the `docker-compose.dev.yml` bind-mount, so the console served the Sep 29 image (old N logo and topology), the operator saw a stale UI, and the first drill result was invalid. The container was recreated with the dev override, the mount was verified, and the drill was re-run. No source or data was lost; arenas were untouched (`--no-deps`).

**Files:** `cyber-range/webui/app.py`, `docker-compose.yml`, `cyber-range/webui/frontend/src/{main.tsx,styles.css,research/index.tsx}`, `tests/test_webui.py`, `README.md`, `cyber-range/webui/frontend/README.md`, `docs/UI_REBUILD_PLAN.md`, `ISSUES.md`.

**Verification:**
- **Tests:** a new WebUI test for the legacy escape failed first, then passed. A fresh-interpreter test asserts the default is the console when the variable is unset. The legacy-home tests pin the switch to false explicitly. The full `tests/test_webui.py` passes.
- **Live fallback drill (dev stack, bind-mount verified):** with false, `/` → 200 legacy; with true, `/` → 302 `/console`, `/?legacy=1` → 200 and `/console` → 200. Login lands on `/console`.
- **Browser checks:** Release B/D/G/H, the stepper check, Prettier and `git diff --check` pass. The pinned gate for Release H passed earlier today; this change only touches the default switch, tests and frontend layout.

**Unresolved risks / next step:** UI-R1 stays open for the items it still names: setup command output, the custom topology builder and non-Docker-local launches still use legacy pages; forwards, archive removal and destroy-from-list have not been exercised against the live service; a formal accessibility review has not been recorded. Commit the branch as whole-phase commits when the operator asks.

## 2026-10-07 — Release H: complete console menus, Forge FX and sign-in

**Outcome:** Operator asked for refinement, FX, quality and personality, and for every menu to be completed before a manual review that may make `/console` the default. Parity gaps were inventoried against the legacy pages first. New console-native views:
- **Arena:** Score & trace (assessment with mode/progress/confirmed/fault sites, milestones and signal counts; ground-truth Challenges hidden behind an explicit Reveal; self-declared run attribution with the eval-export link) and Service forwards (open a 120-second lease from a foothold, list and revoke leases, local client command). The Access tab gains the agent connect recipe with copy buttons.
- **All arenas** (`/console/arenas`): All/Live/Archived filters, search, destroy (live) and remove/clear archive (terminal records), each behind the in-page confirm dialog.
- **All evaluations** (`/console/evaluations`): every comparison with builds, suite and a state filter. Both pages are in the Library menu, and every former `/engagements` and `/evaluations` link now points at them.
- **Research home:** a Host & arenas capacity panel. Activity gains verdict and source filter chips.
- **Sign-in:** the Flask login page is now a Forge plate with the same form contract (username, password, CSRF token, `next` handling).
- **FX:** topology edges draw in from the foothold, panels and step rails enter in sequence, controls press, gold buttons get a brass sheen, the live dot pulses, and loading uses Forge-shaped skeletons. All of it is off under reduced motion.
- **Smaller changes:** the arena header's "Open all arena controls" became a subtle "Legacy arena page" link, because setup command output, the custom topology builder and non-Docker-local launches remain legacy-only. The Cyber Range Purpose hint now states that purpose is recorded for audit only and does not change scoring, containment or limits (verified in `api.py` and `scoring.py`).

**New BFF routes:** `GET /api/console/arenas/<id>/score|trace`, `GET/POST /api/console/arenas/<id>/forwards`, `POST …/forwards/<fid>/revoke`, `POST /api/console/archive/<id>/delete`, `POST /api/console/archive/clear`, `gateway_url` in the arena projection, page routes `/console/arenas` and `/console/evaluations`. Each whitelists fields (the score test asserts private explanation text and manifest flags do not leave the server), validates slugs, and relies on CSRF and the orchestrator's own checks. The service only deletes destroyed or failed records.

**Files:** `cyber-range/webui/app.py`, `templates/login.html`, `frontend/src/{main.tsx,ui.tsx,types.ts,styles.css}`, `src/arena/{record.tsx,index.tsx,navigation.tsx,access.tsx}`, `src/shared/lists.tsx`, `src/research/index.tsx`, `src/activity/index.tsx`, `src/range/new.tsx`, `src/benchmark/{index,new}.tsx`, `src/range/index.tsx`, `tests/test_webui.py`, `scripts/ui-release-h-check.cjs`, `scripts/inventory-webui-routes.py`, `docs/UI_ROUTE_ACTION_MATRIX.md`.

**Verification:** Four new WebUI tests failed first, then passed; the full `tests/test_webui.py` passes. `scripts/ui-release-h-check.cjs` passes 25/25 on the live dev stack against both an active mock arena and an archived record. Every destructive or lease POST is intercepted and refused, and the run asserts none were sent. Release B–G, stepper, assistant/rail smoke, TypeScript, Prettier and Vite pass. Live renders at 1440 Day/Night and 390 showed no overflow or console errors. The pinned `make release-check` passed on Python 3.11.14: Ruff and Bandit clean, 970 SQLite tests (4 skipped, 6 deselected), 974 PostgreSQL tests (6 deselected), and migration/API/UI/gateway smoke.

**Unresolved risks / next step:** Forwards, archive removal and destroy-from-list were not exercised against the service (by design during review). Score/Challenges were exercised against a mock arena's real projection only. Setup command output and custom/non-Docker launches still need the legacy page. `WEBUI_DEFAULT_CONSOLE` remains off pending the operator's manual review; UI-R1 remains open.

## 2026-10-07 — Release G (cont.): Forge map on Research, intake stepper, purpose meanings

**Outcome:** Operator requests during live review. The Research home "Active session" panel now draws the same Forge `SegmentMap` as the Arena page from the arena projection (`/api/console/arenas/<id>`), replacing the icon-only mini topology. `/console/research/new` is a three-step Forge stepper (Target → Consent & limits → Review & launch) with a brass step rail, a navy "How it works" plate per step, per-step validation, Back/Next, and a review step showing the pinned identity and the Forge map of the previewed topology before Launch. The intake request, preview, pinning and launch logic are unchanged; the single-page form remains at `?layout=form` for A/B comparison. On Cyber Range → Launch, Purpose keeps its names (operator choice) but "Research" is labelled "Manual research" and each option shows its service meaning. A mock-provider arena `forge-review` (2d68afe3) was launched on the dev stack for browsing; no containers were created.

**Files:** `cyber-range/webui/frontend/src/research/{index.tsx,new.tsx}`, `src/range/new.tsx`, `src/arena/forge.tsx` (exported `stationDetail`), `src/styles.css`, `scripts/ui-release-g-stepper-check.cjs`.

**Verification:** `scripts/ui-release-g-stepper-check.cjs` 15/15 (mocked preview; launch never clicked). It found two defects before passing: hidden step groups still displayed (`display: grid` beat `[hidden]`), and native form validation silently blocked Next on a hidden required checkbox (stepper form is now `noValidate` with per-step validation). Release B–G checks, assistant/rail smoke, TypeScript, Prettier, Vite and `git diff --check` pass. The live Research render was checked without mocks at 1440 Day/Night (map) and 1024/390 (station-list fallback, as on the Arena page).

**Unresolved risks / next step:** The stepper was not exercised with a real Git/OCI/bundle preview or launch. The Cyber Range launch preview still uses its narrower panel and falls back to the station list. Awaiting operator approval; UI-R1 remains open.

## 2026-10-07 — Release G: workflow pass inside the approved Forge look

**Outcome:** Applied the functional findings of the 2026-10-07 legacy-vs-Royal-Command audit without palette, bar, typography or surface changes. Arena tool row: tools that cannot use the selected station are dashed and muted with no launch arrow (still openable to read records); ready tools keep a brass edge. The assistant launcher loads the model connection on mount and shows a status dot (accessible name stays "Research assistant"; state is in its description and tooltip); the footer reserves space so the page end is clear of the launcher. Revoke (Agent access) and Finish setup use a new in-page `ConfirmDialog` instead of `window.confirm`. Research home gains a "05 / Activity" panel (latest attributed events, All/Agents/Human/System filter, newest first), and its Needs review / findings / Proof desk links open console routes instead of legacy pages. Benchmark home gains a Builds → Challenges → Suite → Compare step strip marking the first unmet step. Status pills no longer stretch in grid cells; counts and station facts use tabular figures. Token `--purple` (now brown) renamed `--accent`; z-index values use a named scale. Awaiting the operator's manual approval. The warm-charcoal Night proposal (A/B "B") was rejected by the operator as out of tune; instead, Night keeps its navy page and the Forge plates (Arena workbench, Research featured, Benchmark latest) get a brass edge and deeper drop, applied live in `/console` for in-browser review. Moving the phone launcher into the bar remains a proposal only.

**Files:** `cyber-range/webui/frontend/src/{ui.tsx,styles.css}`, `src/arena/{forge.tsx,forge.css,navigation.css,setup.tsx,access.tsx}`, `src/research/index.tsx`, `src/benchmark/index.tsx`, `src/shared/{assistant.tsx,assistant.css}`, `scripts/ui-release-g-check.cjs`, renders `docs/assets/ui-concepts/renders/release-2026-10-07g-*.png` (incl. `proposal-nightB-*`). Viewable mock: https://claude.ai/artifact/CRLacLB7eURYyEaEYLSgBx (private).

**Verification:** `scripts/ui-release-g-check.cjs` failed 11/20 against the previous build, then passed 23/23 three runs in a row. Release B (17/17), C (23/23), D (22/22), E (20/20), F (10/10), the assistant/rail smoke, TypeScript, Prettier, Vite and `git diff --check` pass. All projections were mocked; no lifecycle, revoke, setup or model request reached the service. Frontend-only; `make release-check` was not rerun (Release D remains the backend evidence).

**Unresolved risks / next step:** On phones the fixed launcher can still overlay content mid-scroll. "View all" sessions/evaluations and "Open all arena controls" still go to legacy pages. The Benchmark step strip repeats the Registry panel counts; consider trimming one after review. UI-R1 remains open.

## 2026-10-02 — Release F: tidy tool row and lifecycle text, monitor signals

**Outcome:** Addressed the operator's polish notes: the loose "Tools for <station>" caption is gone; tool buttons show a short status ("Use api", "Unavailable here", "No web service", "Attacker station", "Archived record") at equal widths on desktop, with the full reason in the tooltip and accessible name. The reset reason no longer sits loose beside the lifecycle buttons; Arena actions shows Reset as unavailable with a readable reason ("Unavailable: missing immutable inputs or readiness policy"), including on archived records. Added a collapsible "Monitor signals" row above the event trace using the service's recorded monitor signals (count, latest summary; expanded list with time, severity and node; explicit empty and unavailable states). No "Run preflight" action was added: the preflight endpoint returns the recorded setup preflight, not a live check, so a button would misrepresent it. Awaiting the operator's manual approval.

**Files:** `cyber-range/webui/frontend/src/arena/{forge.tsx,forge.css}`, `scripts/ui-release-f-check.cjs`, updated `scripts/ui-release-{c,d}-check.cjs`, renders `docs/assets/ui-concepts/renders/release-2026-10-02f-*.png`.

**Verification:** `scripts/ui-release-f-check.cjs` failed first (no reset explanation in the menu), then passed 10/10 with mocked arena and evidence projections. Release B–E checks, the assistant/rail smoke, TypeScript, Prettier and Vite pass. Frontend-only; the Release D pinned gate remains the backend evidence.

**Unresolved risks / next step:** Monitor signals were shown with mocked data; the dev stack's records have none. Candidates next: assistant panel docking, or the Cyber Range preview using the station facts. UI-R1 remains open.

## 2026-10-02 — Release E: explicit target handoff from the map to tools

**Outcome:** In the Forge inspector, each tool that can use the selected station offers a named link ("Use api in HTTP", "Use db in PoC"); ineligible tools and the attacker station get none. Following it opens the tool with `?target=<station>` and preselects that station in HTTP, Browser or PoC, with a "Target from map" notice. A station the tool cannot use is refused with a reason and is not silently swapped. Changing the target by hand removes the map origin from the URL and the notice. Nothing is submitted by the handoff; the service still authorizes every request. Roles that are acronyms display in capitals (API, DNS, LDAP…). After operator feedback about empty space, the per-station tool list moved out of the inspector into the workbench row ("Tools for api": each tool shows "Use api" or why it cannot be used), and the map height now follows its stations: the panel shrank from 510 to 378 px (archived record) and 560 to 437 px (mock pivot), and the empty band under the workbenches fell from about 130 px to at most 36 px. Approved by the operator on 2026-10-02; the "Tools for <station>" label and the loose reset reason were flagged as unpolished and are addressed in Release F.

**Files:** `cyber-range/webui/frontend/src/arena/{target.tsx,forge.tsx,forge.css,http.tsx,browser.tsx,poc.tsx}`, `src/styles.css`, `scripts/ui-release-e-check.cjs`, renders `docs/assets/ui-concepts/renders/release-2026-10-02e-*.png`.

**Verification:** `scripts/ui-release-e-check.cjs` failed first (no handoff link), then passed 16/16 three runs in a row after its mock was changed to fetch the base record once (a first run had failed on a fetch racing navigation). Its new empty-space checks failed at 148/126 px before the layout fix and pass now (20/20). It asserts no HTTP, Browser or PoC request is sent. Release B/C/D checks, the assistant/rail smoke, TypeScript, Prettier and Vite pass. Frontend-only change; the last pinned gate (Release D) remains the backend evidence.

**Unresolved risks / next step:** Exercised with mocked active records only; a live Docker-local handoff and request remain unexercised. UI-R1 remains open.

## 2026-10-02 — Release D: topology adapts to the spawned scenario

**Outcome:** The arena projection now carries tester-facing station facts from the pinned lifecycle recipe, status outputs and capability manifest: role, image and pin status, declared ports, networks, private IP, readiness, a published URL for live records only, and per-arena HTTP/Browser/PoC/file/forward/exec/setup/observe availability with the service's reason. SSH commands, environment key names and credentials stay server-side. The Forge map uses a new layered layout (`topology/layout.ts`): columns alternate stations and networks by hop from the attacker foothold, so pivots and hosts on several networks read left to right; stations keep a fixed size, wide arenas scroll inside the panel with a "Map continues" cue, and column labels distinguish pivot from target columns. Station boxes show role and ports. The inspector shows those facts plus "Tools for this station" with the reason each tool can or cannot be used. Reset reasons are readable text. Approved by the operator on 2026-10-02 ("Continue").

**Files:** `cyber-range/webui/app.py`, `tests/test_webui.py`, `cyber-range/webui/frontend/src/topology/{layout.ts,SegmentMap.tsx}`, `src/arena/{forge.tsx,forge.css}`, `src/types.ts`, `src/styles.css`, `scripts/ui-release-d-check.cjs`, renders `docs/assets/ui-concepts/renders/release-2026-10-02d-*.png`.

**Verification:** Two new WebUI projection tests failed first, then passed. `scripts/ui-release-d-check.cjs` passes 22/22 against mocked 6-station (three networks, a bridging host, an unlinked station) and 14-station arenas plus the real record. Note: this browser check was written after the frontend change, so it was not observed failing first. Release B/C checks, the assistant/rail smoke, TypeScript, Prettier and Vite pass. The pinned `make release-check` passed: 966 SQLite tests (4 skipped, 6 deselected), 970 PostgreSQL tests (6 deselected) and smoke.

**Unresolved risks / next step:** Only mocked multi-network arenas were rendered; a real Docker-local multi-segment scenario is still unexercised. The Cyber Range preview uses the same layout without the new station facts. Selecting a station does not yet hand its target to HTTP/Browser/PoC. UI-R1 remains open.

## 2026-10-02 — Release C: Forge is the single Arena home

**Outcome:** `/console/arena/<id>` now opens the Forge view with the Prepare / Investigate / Record rail on every tool; the old Overview grid, the long tab strip, the "Forge preview" tab and the `layout=forge` switch are gone (`?tab=forge` still works). Content that only the Overview had moved into Forge: recent findings with verdicts and the PoC job count in the record row, the reason a reset is unavailable, and the lifecycle result with the "Open replacement arena" link, now shown as a status row above any Arena view. The disabled "Fuzz · planned" tile was dropped. The Arena actions menu closes after an action is chosen. 58 CSS selectors used only by the removed views were deleted. Approved by the operator on 2026-10-02.

**Files:** `cyber-range/webui/frontend/src/arena/{index,forge,navigation,setup}.tsx`, `arena/forge.css`, `main.tsx`, `styles.css`, `scripts/ui-release-c-check.cjs`, renders `docs/assets/ui-concepts/renders/release-2026-10-02c-*.png`.

**Verification:** `scripts/ui-release-c-check.cjs` failed first (no rail on the plain Arena URL), then passed 23/23 using mocked arena records and a mocked reset response (no lifecycle request reached the service). Release B checks (17/17), the assistant/rail smoke, TypeScript, Prettier and Vite pass.

**Unresolved risks / next step:** "Open all arena controls" still links to the legacy arena page (needed until UI-R1 parity). Mocked active renders reuse the archived record's station states. Next: Release D, adaptive topology with clear scenario information for the tester.

## 2026-10-02 — Release B: readable topology, truthful assistant status, compact launcher

**Outcome:** Functional fixes within the approved look. Topology stations are drawn at a fixed 184×70 px with 14 px names; only the column spacing follows the available width (540–1000 px, centred above). Below 540 px the panel shows the readable network list and station buttons instead of shrinking or scrolling. The assistant status line now reports the connection (checking, unavailable, "Connect a model to ask questions.", "Ready for your question.") instead of saying "Ready when a model is connected" while connected. Below 1280 px the closed launcher is a 44 px icon button with the same accessible name; wider screens keep the labelled button. Topology counts pluralize. Approved by the operator on 2026-10-02.

**Files:** `cyber-range/webui/frontend/src/topology/SegmentMap.tsx`, `src/styles.css`, `src/shared/assistant.tsx`, `src/shared/assistant.css`, `scripts/ui-release-b-check.cjs`, renders `docs/assets/ui-concepts/renders/release-2026-10-02b-*.png`.

**Verification:** `scripts/ui-release-b-check.cjs` failed 5/17 before the change (station 134 px wide at 1024 vs 266 px at 1920, 11 px names, wrong connected status, full-width launcher at 1024/390), then passed 17/17. `scripts/ui-assistant-rail-smoke.cjs`, TypeScript, Prettier and Vite pass. Model responses were mocked; no provider was contacted and nothing was launched.

**Unresolved risks / next step:** Only two-node archived records exist on the dev stack, so N-node layout is still the two-column recipe view; the layered topology and target handoff remain planned. The open assistant panel still overlays the inspector at desktop widths. UI-R1 remains open.

## 2026-10-02 — Release A: anvil brand, centred workspaces, no mock strip

**Outcome:** On the restored Royal Command look: removed the global mock-mode strip (mock state stays labelled on the Cyber Range notice, arena subtitle and intake form). Replaced the "N" tile with the anvil emblem, using a new transparent, cropped copy `cyber-range/webui/static/anvil_emblem.png` (the original `anvil_logo.png` is unchanged). Centred Research, Benchmark and Cyber Range on the bar at 1180 px and wider; the compact and phone layouts keep their existing grouping. Approved by the operator on 2026-10-02 after manual review.

**Files:** `cyber-range/webui/frontend/src/main.tsx`, `src/styles.css`, `cyber-range/webui/static/anvil_emblem.png`, renders `docs/assets/ui-concepts/renders/release-2026-10-02a-*.png`.

**Verification:** TypeScript, Prettier and Vite pass; `scripts/ui-assistant-rail-smoke.cjs` passes. Chromium measured the workspace group centred within 2 px of the bar centre at 1440, 1280 and 1200 px in Day and Night, with no document overflow at 1440/1280/1200/1024/390.

**Unresolved risks / next step:** UI-R1 remains open. Each further release pauses for manual approval.

## 2026-10-02 — Forge foundations attempt rejected and reverted

**Outcome:** Implemented checkpoint C1 of the UI audit (cool navy-tinted Day tokens, Geist and runic fonts, a refitted 56 px bar, theme-locked Forge surfaces, removal of numbered labels and decoration). The operator rejected it: it looked worse than before, the bar lost its character, and making Forge surfaces follow the light theme removed the navy-on-stone contrast that made the console look good. The frontend was restored to its pre-C1 state. The only change kept is the shared-resource links (Targets, Agents, Evidence, Activity), now always in a **Library** dropdown instead of inline links. The legacy backup is untouched.

**Lesson for later work:** keep the navy Forge plate on the warm stone Day page, the brass-boxed active workspace and the existing bar proportions. Propose further visual changes as side-by-side A/B renders before applying them.

**Files:** `cyber-range/webui/frontend/src/main.tsx` and `styles.css` (Library menu). Rejected attempt kept for reference: [plan](superpowers/plans/2026-10-02-ui-forge-foundations.md), [verification](verification/ui-forge-foundations-2026-10-02.md), `scripts/ui-foundation-smoke.cjs` (encodes the rejected direction; not a gate) and `foundation-*-2026-10-02.png` renders.

**Verification:** After the revert, TypeScript, Prettier, Vite and `scripts/ui-assistant-rail-smoke.cjs` pass. The pinned `make release-check` passed during the attempt (964 SQLite, 968 PostgreSQL); the revert changed frontend files only.

**Unresolved risks / next step:** UI-R1 remains open. The audit's functional findings (topology scaling, target handoff, assistant status line and overlap, setup history) still stand; visual direction needs operator selection from A/B renders first.

## 2026-10-01 — Restore the research assistant and contextual Arena navigation

**Outcome:** Restored a global React Research assistant with inline BYO model connection, masked status, arena-aware streamed chat, stop/clear controls and conversation continuity across same-arena tools. Reused the existing Flask/service credential and chat boundaries. Added Prepare/Investigate/Record category navigation to the Forge preview, keyboard/hover/click flyouts, responsive category navigation, and compact setup-phase rendering. Fixed route reconciliation when returning to an already-selected primary workspace. The prototype remains opt-in; the wider rollout awaits review.

**Files:** `cyber-range/webui/frontend/src/shared/assistant.tsx`, `assistant.css`, `arena/navigation.tsx`, `navigation.css`, `arena/index.tsx`, `arena/setup.tsx`, `arena/forge.css`, `main.tsx`, `scripts/ui-assistant-rail-smoke.cjs`, [verification and renders](verification/ui-assistant-navigation-2026-10-01.md), and this journal.

**Verification:** TypeScript, Prettier, Vite, browser-script syntax and `git diff --check` passed. Browser tests used synthetic credentials, mocked model replies and mocked setup states; verified connection form/key clearing/CSRF, text escaping, failed-turn recovery, same-arena chat continuity, keyboard dismissal, setup phases/defaults, and navigation/assistant reflow at 1024, 760, 390 and 320 px. The final pinned release gate on 2026-09-30 passed Ruff, source-only Bandit, 964 SQLite tests (4 skipped, 6 deselected), 968 PostgreSQL tests (6 deselected), and smoke. The restarted session completed the interrupted browser check without repeating model writes or infrastructure operations.

**Unresolved risks / next step:** No real provider was contacted; real model streaming/cancellation remains unverified here. Chat history is memory-only and clears on refresh or changed arena context. Setup/lifecycle mutations were not exercised by this visual checkpoint. Keep UI-R1 open and await operator review before extending the approved shell to the remaining workspaces.

## 2026-09-30 — Refine Forge proportions around researcher tasks

**Outcome:** The approval preview now uses a slim wrapping arena summary, a shorter topology canvas and a compact station inspector. Removed the duplicate workbench banner, desktop station buttons when graph selection is available, and planned Fuzz controls. HTTP/Browser/PoC are grouped below the canvas; Findings and Evidence share a record row. Station metadata and event trace expand on demand. Reset/Destroy are grouped in Arena actions while Stop/Resume stays visible for active records, using the existing confirmation flow.

**Files:** `cyber-range/webui/frontend/src/arena/forge.tsx`, `forge.css`, `topology/SegmentMap.tsx`, revised renders and recording linked in [prototype review](verification/ui-forge-prototype-2026-09-30.md), and this journal.

**Verification:** TypeScript, Prettier, Vite and `git diff --check` passed. Chromium verified keyboard/pointer station selection, trace expansion, reduced motion, and no document overflow with station selection at 1024, 760, 390 and 320 px. The final pinned release gate passed Ruff, source-only Bandit, both SQLite and PostgreSQL suites (968 PostgreSQL tests passed, 6 deselected), and smoke.

**Unresolved risks / next step:** The preview remains an archived mock record and does not verify live lifecycle operations. UI-R1 stays open. Await visual approval of these revised proportions before extending this design across the other workspaces.

## 2026-09-30 — Deliver the first interactive Forge Arena approval checkpoint

**Outcome:** Added an opt-in `tab=forge` Arena composition: one connected topology/inspector surface, selectable stations, compact tool strip, evidence summary and collapsible event trace. Restored the original emblem inside the workbench. Selection, hover, focus and trace motion respect reduced motion. Existing lifecycle confirmations and tool routes are reused; selection does not silently scope tool operations. The existing overview remains available for comparison. Work stops at the operator's requested approval boundary before redesigning the other sections.

**Files:** `cyber-range/webui/frontend/src/arena/forge.tsx`, `forge.css`, `arena/index.tsx`, `topology/SegmentMap.tsx`, [prototype evidence](verification/ui-forge-prototype-2026-09-30.md), day/night/phone renders, interaction recording and this journal.

**Verification:** TypeScript, Prettier, Vite and `git diff --check` passed. Chromium verified pointer and keyboard station selection, trace expansion, reduced motion and no desktop JavaScript errors; station selection and no document overflow passed at 1024, 760, 390 and 320 px. The pinned release gate passed Ruff, source-only Bandit, 964 SQLite tests (4 skipped, 6 deselected), 968 PostgreSQL tests (6 deselected) and smoke.

**Unresolved risks / next step:** The captured environment is an archived mock arena. Live lifecycle operations were not exercised in this visual checkpoint. UI-R1 remains open; await the operator's visual approval, then extend the approved composition across the remaining workspaces and verify their full workflows.

## 2026-09-30 — Make topology and workspace navigation legible

**Outcome:** The opt-in console now renders an attacker–network–target SVG topology from operator-safe declared segment membership in Cyber Range and arena overview. Archived arena stations report archived state. The Range preview is the primary work surface beside its scenario catalog. Shared Targets, Agents, Evidence and Activity access moved into the command bar, with a narrower-screen Tools menu; the profile menu holds only account and platform settings. Day surfaces use warm stone, brass and royal navy while the night option remains.

**Files:** `cyber-range/webui/app.py`, `cyber-range/webui/frontend/src/topology/SegmentMap.tsx`, arena and Range components, `cyber-range/webui/frontend/src/main.tsx`, `cyber-range/webui/frontend/src/styles.css`, `tests/test_webui.py`, [render review](verification/ui-topology-polish-2026-09-30.md) and this journal.

**Verification:** TypeScript, Prettier and production Vite build passed. The pinned `make release-check` passed Ruff, source-only Bandit, 964 SQLite tests (4 skipped, 6 deselected), 968 PostgreSQL tests (6 deselected) and smoke. Chromium showed no document overflow or JavaScript errors on Research, Benchmark, Cyber Range and Arena at 390 and 320 px. The linked review contains desktop and phone renders.

**Unresolved risks / next step:** UI-R1 stays open: inspect the new composition with researchers, manually review accessibility, exercise failure and denial states, complete route/action parity and the default/fallback drill. The captured arena is archived mock data; retain `/console` as opt-in until cutover criteria pass.

## 2026-09-29 — Exercise live Research and Benchmark console journeys

**Outcome:** Chromium completed a Docker-local source-bundle Research path from
upload and immutable review through setup, a succeeded confined PoC, finding,
teardown and archived inspection. A separate isolated stack completed a
three-pair, six-trial scripted calibration Benchmark comparison through the
React registry and comparison screens. The live Research run exposed an arena
event `type` filter gap; the service now applies it before limiting results.
The disposable NV-02 stack's zero-minute stuck reaper was raised to five
minutes. Benchmark result labels and number precision were made readable, and
phone metrics now stack as cards.

**Files:** `cyber-range/services/scenario-orchestrator/api.py`,
`docker-compose.nv02.yml`, `tests/test_api.py`,
`cyber-range/webui/frontend/src/benchmark/detail.tsx`,
`cyber-range/webui/frontend/src/styles.css`,
`docs/verification/ui-research-benchmark-live-2026-09-29.md`, new live renders,
`docs/UI_REBUILD_PLAN.md`, `ISSUES.md` and this journal.

**Verification:** The live Research PoC reached `succeeded`. The Benchmark
comparison completed six trials with three matched pairs, zero infrastructure
failures and a +1 verified difference labeled with a degenerate interval.
Chromium found no page overflow or JavaScript exceptions for the live archive
and result at 1440, 1024, 390 and 320 px. All tested arenas had zero labeled
containers and networks after teardown; both isolated stacks and volumes were
removed. The final pinned `make release-check` passed Ruff, source-only Bandit,
963 SQLite tests (4 skipped, 6 deselected), 967 PostgreSQL tests (6
deselected), and migration/API/UI/gateway smoke. TypeScript, Prettier, Vite
build and `git diff --check` also passed.

**Unresolved risks / next step:** UI-R1 remains open for route/action parity,
browser failure/denial states, manual accessibility and researcher observation,
and the fallback drill. Keep `/console` opt-in until those cutover gates pass.

**Cutover preparation:** `WEBUI_DEFAULT_CONSOLE=true` now redirects the legacy
home route to `/console`, while `false` restores the original home and all
legacy routes remain mounted. The switch is disabled by default. A WebUI
test covers both states and the retained `/engagements` route; a live
deployment fallback drill remains open.

## 2026-09-29 — Carry Research setup consent into the workbench

**Outcome:** The opt-in setup workbench now receives the reviewed mode, time
box, command budget and egress choice from the arena's setup prearm record.
Its start form uses those values when the operator has not edited them. A
finished setup shows a retained-record state instead of offering another
start action. The browser projection excludes the prearm artifact and other
private event fields.

**Files:** `cyber-range/webui/app.py`,
`cyber-range/webui/frontend/src/arena/setup.tsx`, `tests/test_webui.py` and
this journal.

**Verification:** TypeScript, Prettier, Vite build and `git diff --check`
passed. The pinned `make release-check` gate passed Ruff, source-only Bandit,
962 SQLite tests (4 skipped, 6 deselected), 966 PostgreSQL tests (6 deselected),
migration and API/UI/gateway smoke. The projection test checks planned values,
finished state and private-field omission.

**Unresolved risks / next step:** A complete Docker-local Research bundle
intake, setup and finding journey still needs Chromium evidence. UI-R1 remains
open. The new console remains opt-in at `/console`; the legacy layout remains
the default until the migration acceptance gates pass.

## 2026-09-29 — Label mock Research intake accurately

**Outcome:** The opt-in Research intake now names the mock simulator when the
development stack runs with `MOCK_MODE`, while the Docker-local wording remains
for a real provider. This removes a misleading provider claim in the target
review form.

**Files:** `cyber-range/webui/frontend/src/research/new.tsx` and this journal.

**Verification:** TypeScript, Prettier, the Vite production build and the
packaged WebUI Docker build passed.
Chromium on the running mock development stack displayed the simulator wording
and the `MOCK` label on `/console/research/new`; a visible-control name scan
of 12 console routes found no unnamed controls. The earlier pinned Python
release gate remains the most recent backend gate; this edit is frontend-only.

**Unresolved risks / next step:** A Docker-local Research intake and setup
journey is still needed under UI-R1. Keep the new console opt-in until the
remaining parity, accessibility and fallback checks pass.

## 2026-09-29 — Verify Docker-local Cyber Range UI and repair HTTP ledger

**Outcome:** An isolated PostgreSQL-backed Docker-local stack completed a
React Cyber Range journey from scenario import through launch, HTTP request,
linked finding, reset, retained original record and replacement teardown.
The live run exposed a mismatch between HTTP list manifests and full envelopes
that crashed the HTTP tab when a transaction existed. The ledger now renders
manifests and retrieves an envelope only when inspecting or replaying. The
live render also exposed naive UTC timestamps displayed as local time; the
shared date formatter now shows expiry and observation in one time zone. The
fixture scenario was deleted and the isolated stack was removed.

**Files:** `frontend/src/arena/http.tsx`, `frontend/src/{types.ts,ui.tsx}`,
`docs/verification/ui-docker-local-2026-09-29.md`, the live arena render,
`docs/assets/ui-concepts/README.md`, `docs/UI_REBUILD_PLAN.md`, `ISSUES.md`
and this journal.

**Verification:** Chromium used the packaged WebUI against the real worker and
Docker provider. The original and replacement arena reached `active`; the
original retained its finding after reset, the replacement reached
`destroyed`, and both IDs had zero labelled containers/networks. `npm run
check`, Vite production build and isolated packaged WebUI rebuild passed after
the ledger and time fixes. The final live render showed observation at 9:47 AM
and expiry at 10:47 AM for the one-hour arena. The isolated Compose project
and volumes were removed; its
`compose ps` is empty. The earlier pinned Python release gate passed before
the frontend-only ledger fix. See the dated verification note for IDs and
scope.

**Unresolved risks / next step:** UI-R1 remains open. Run the Docker-local
Research and Benchmark browser paths and complete parity, accessibility,
usability and fallback evidence before default cutover.

## 2026-09-29 — Show live Benchmark trial progress and failures

**Outcome:** The opt-in Benchmark evaluation detail now refreshes while a
queued/running suite progresses, stops polling after completion, and shows
trial counts, build side, challenge identity and bounded operational failure
reasons. A completed run with no matched pair now explains why no difference
is reported. The projection remains operator-only and excludes private truth,
trial transcripts and worker claims.

**Files:** `cyber-range/webui/app.py`,
`frontend/src/benchmark/detail.tsx`, `frontend/src/{types.ts,ui.tsx,styles.css}`,
`tests/test_webui.py`, `docs/UI_REBUILD_PLAN.md`, the evaluation progress and
failure renders, `docs/verification/ui-evaluation-progress-2026-09-29.md`,
the render gallery and this journal.

**Verification:** `npm run check`, Vite production build, packaged WebUI Docker
build and `git diff --check` passed. Pinned `make release-check` passed: Ruff
and Bandit clean; SQLite 962 passed, four skipped and six integration
deselections; PostgreSQL 966 passed, six integration deselections; migration,
API, UI and gateway smoke passed. Chromium fixture responses verified the
running-to-complete refresh in two reads, a visible infrastructure failure,
and no document overflow at 1440, 390 or 320 px. A control-name scan of 12
main routes found no visible unnamed interactive controls; it is not a WCAG
audit.

**Unresolved risks / next step:** UI-R1 remains open. A real Docker-local
paired evaluation through the new UI and full parity, accessibility, usability
and fallback evidence remain prerequisites for default cutover.

## 2026-09-29 — Add Royal Command scenario library and import review

**Outcome:** The opt-in Cyber Range now has a searchable scenario library with
topology review and an authoring screen for pasted v3 specs, offline or
repository Vulhub sources, and model-generated drafts. Import requires a valid
preview of the current source; editing disables the save action until the
operator validates again. Generated drafts remain editable and comparable with
their original text. Imported packs can be deleted after confirmation. The
older aesthetic remains in its dated backup, and the default layout remains
unchanged.

**Files:** `cyber-range/webui/frontend/src/range/{library,import,topology}.tsx`,
`frontend/src/{api.ts,main.tsx,types.ts,styles.css}`,
`cyber-range/webui/app.py`, `tests/test_webui.py`, the route inventory and
generator, `docs/UI_REBUILD_PLAN.md`, the scenario review renders,
`docs/verification/ui-scenario-authoring-2026-09-29.md`, and this journal.

**Verification:** The pinned `make release-check` passed: Ruff and Bandit
clean; SQLite 962 passed with four PostgreSQL-specific skips and six
integration deselections; PostgreSQL 966 passed with six integration
deselections; migration/API/UI/gateway smoke passed. Chromium on the running
`MOCK_MODE` development stack completed preview/import/topology/delete for a
temporary v3 pack and validated an offline Vulhub Compose preview. Editing the
reviewed source disabled import. Reflow checks found no document overflow on
the import screen at 1440, 1024, 390 or 320 px and on the library at 1024,
390 or 320 px. The temporary registration was removed. The packaged WebUI
Docker image built with its pinned Node stage.

**Unresolved risks / next step:** UI-R1 remains open. Prove the complete
Docker-local Research, Benchmark and Cyber Range journeys, including scenario
launch/reset/archive, and finish old action/deep-link parity, accessibility
and usability review, and the fallback drill before switching the default.

## 2026-09-28 — Add arena browser and transfer workspaces

**Outcome:** Added isolated browser visits and bounded foothold file transfer
to the opt-in Royal Command arena. Browser responses show escaped DOM, title,
byte count, truncation and digest. Uploads produce a digest receipt and a link
that preloads the uploaded path into the PoC form. Downloads assemble bounded
chunks and verify the complete SHA-256 digest before offering a file. Narrow
same-origin BFF routes retain the orchestrator's node, path and access checks;
the browser never receives an orchestrator key. Fixed login redirects so
protected console links keep their query string, including intake source
links, while rejecting external redirect targets. The arena's active tab now
scrolls into view on small screens. The dated legacy aesthetic reference
remains saved and the new console remains opt-in. A shell-wide status strip,
Cyber Range forms and arena views now label `MOCK_MODE` simulation explicitly,
so a simulated launch is not presented as Docker-local infrastructure evidence.

**Files:** `cyber-range/webui/app.py`, `frontend/src/arena/{browser,transfer,index,poc}.tsx`,
`frontend/src/styles.css`, `tests/test_webui.py`, `docs/UI_ROUTE_ACTION_MATRIX.md`,
`docs/UI_REBUILD_PLAN.md`, `docs/assets/ui-concepts/README.md`, the Browser and
Transfer renders, `docs/verification/ui-royal-command-2026-09-28.md`,
`ISSUES.md`, and this journal.

**Verification:** Focused BFF tests covered CSRF, bounds, response projection
and redirect safety. Fixture-backed Chromium checked Browser and Transfer
actions at 1440, 390 and 320 px, including escaped DOM, digest-mismatch
rejection and PoC prefill. A separate disposable mock API database served
Research, Benchmark, Cyber Range, Targets and Settings in Chromium and
accepted a real source-bundle upload/preview; it had no worker, so no launch
or arena lifecycle was claimed. `npm run check`, the packaged WebUI Docker
build and `git diff --check` passed. The final pinned `make release-check`
passed: Ruff and Bandit clean; SQLite 962 passed, four PostgreSQL-only skips
and six integration deselections; PostgreSQL 966 passed with six integration
deselections; migration/API/UI/gateway smoke passed.

The running development SQLite schema was compared with a fresh Alembic `0009`
database. Only two nullable columns and the version table differed; indexes
matched. The repair was rehearsed on a disposable SQLite copy, including
integrity and authenticated API reads. Services were stopped, a fresh backup
was saved at `/tmp/nv-ui-development-backup-2026-09-28.db` with mode 0600,
the two columns were added and Alembic stamped `0009`; integrity passed and
both existing deployments remained. Services restarted. Chromium loaded
Research, Benchmark, Cyber Range, Targets and Settings from the running Compose
stack; their BFF data requests returned HTTP 200.

Chromium then launched `ui-smoke-20260928` through the React Cyber Range form
in that mock stack, opened the arena plus Browser and Transfer tabs with HTTP
200 data requests, and destroyed it through the React confirmation dialog.
The retained record reported `destroyed`; this tested the simulated UI path,
not Docker-local node/browser/file execution. The live console bundle was
rebuilt in its mounted development source after the UI changes. Chromium
confirmed the simulation labels on Cyber Range and the retained arena.

**Unresolved risks / next step:** UI-R1 now tracks the remaining live-journey
proof. Live Docker-local Browser/Transfer and end-to-end Research, Benchmark
and Cyber Range tasks,
exact legacy action/deep-link parity, accessibility/usability review and a
fallback drill remain required before switching the default layout. Verify the
browser task paths and record the result in `docs/verification/`.

## 2026-09-28 — Expand Royal Command coverage and preserve the prior console

**Outcome:** Extended the opt-in React console with source-bundle upload, digest
review and launch; an HTTP capture/replay workspace; Benchmark build/challenge/suite
registry; shared Targets, Agents, Activity, Settings and Profile screens; and arena
Setup, Agent Access, Infrastructure and source diff views. Source diff can export a
content-addressed patch and prefill its digest in a finding. The arena now listens
to its existing SSE stream for state/activity refresh, with a bounded polling
fallback during reconnect. React code is split into feature folders, shared UI,
types and a same-origin request client. The older Jinja aesthetic is saved under
`docs/assets/legacy-console-reference/2026-09-28/` with desktop/phone fixture
captures and a SHA-256 manifest, before any default-layout switch.

**Files:** `cyber-range/webui/frontend/src/{activity,arena,benchmark,range,research,shared}/`,
`src/{main,api,types,ui,styles}` under that frontend, `cyber-range/webui/app.py`,
`tests/test_webui.py`, `docs/UI_REBUILD_PLAN.md`,
`docs/UI_ROUTE_ACTION_MATRIX.md`, `ISSUES.md`, `docs/assets/ui-concepts/README.md`, the new
review renders, and the dated legacy reference.

**Verification:** Focused WebUI tests, Ruff, TypeScript/Prettier and Vite build
passed. `make release-check` passed on Python 3.11.14 with Ruff and Bandit clean,
SQLite unit tests passing (four PostgreSQL-specific skips), PostgreSQL 963 passed
and six integration deselections, plus migration/API/UI/gateway readiness smoke.
The packaged WebUI Docker build passed. Fixture-backed Chromium exercised the
source-bundle upload/review/launch, setup step, agent grant/pause, HTTP replay,
registry submissions and source diff/patch/finding attachment; shared and arena
screens were checked at 1440, 390 and 320 px without horizontal overflow.
`git diff --check` passed. Browser renders and all legacy backup screenshots use
fixture data; none prove a live arena workflow.

A read-only browser check of the running development Compose stack reached the
new `/console` shell but Research data returned 503. Orchestrator logs show its
persistent SQLite database lacks `model_connections.base_url`; `alembic current`
reported no revision. This pre-existing local schema mismatch prevents live UI
journey verification on that stack. The running database was not changed.

**Unresolved risks / next step:** Royal Command remains opt-in at `/console`.
Browser/transfer tools, old deep links and action/state parity, accessible keyboard
and assistive-tech review, representative researcher observation, real Docker-local
journeys, and the cutover/fallback drill remain open. Verify those against the
route/action matrix before defaulting to the new layout. Keep NV06-R1, NV07-R1
and INFRA-R1 open until their own evidence closes them.

## 2026-09-28 — Restore `/console` in the development stack

**Outcome:** The development WebUI enabled Werkzeug's interactive debugger,
whose default `/console` path intercepted the opt-in Royal Command UI and
showed a debugger PIN prompt. The Flask development reloader now runs without
that debugger, so `/console` reaches the React shell. The README names the
opt-in URL, and the dev Compose comments describe the revised behavior.

**Files:** `cyber-range/webui/app.py`, `docker-compose.dev.yml`, `README.md`.

**Verification:** Restarted the running dev WebUI container. An authenticated
request to `/console` returned HTTP 200 with the React root and no debugger
page. Focused WebUI tests, Ruff and `git diff --check` passed.

**Unresolved risks / next step:** The React console remains opt-in. Complete
the parity and real Docker-local journey checks described below before a
default switch.

## 2026-09-28 — Royal Command Docker-local launch review

**Outcome:** Added an opt-in React launch review at `/console/arenas/new`, linked
from the Cyber Range catalog. It uses the registered scenario topology, collects
arena name, purpose, participant and time box, and submits through a CSRF-protected
Flask BFF. The BFF checks the current catalog, permits only container/any
scenarios for this path, explicitly selects `docker-local`, and returns the
orchestrator's arena UUID. The browser opens that arena's real workspace record.
The legacy launch page remains for other launch and import modes. Saved review
renders now cover Research day/night, Benchmark, Cyber Range, arena workspace,
new arena, comparison, result and mobile stop confirmation. All render data is
declared as fixture data.
The arena workspace also projects reset eligibility and exposes confirmed
reset/destroy requests through the existing service rules; reset results link
to the replacement arena while the original evidence record remains intact.
Research target intake now offers Git and public OCI preview/launch in React.
The preview projects a narrow topology and immutable commit or digest; launch
requires that pinned identity, current authorization confirmation and bounded
setup consent. Source bundles still link to the legacy wizard.
The arena now has an opt-in React PoC view at `?tab=poc` using the existing
confined-job BFF endpoints: source, target relay and limits, submit/cancel,
polling, bounded output, digest and cleanup inspection. The service still
enforces execution access and confinement; archived arenas show job records
without an enabled submission form.
Findings now have a React report/review view. A narrow BFF projection keeps
hidden scenario match data out of the browser while showing reported evidence,
PoC steps, attached digests and independent validation reason. Operators can
record findings and append a confirm/refute verdict; confirmation requires an
immutable evidence digest, and the UI labels manual confirmation separately.
An Evidence tab now inventories attached artifacts, independent effect/control
traces, linked HTTP transactions and monitor signals. Artifact and validation
links use existing arena-scoped proxy routes. The source records remain owned
by the service, including after arena teardown.

**Files:** `cyber-range/webui/app.py`, `cyber-range/webui/frontend/src/main.tsx`,
`cyber-range/webui/frontend/src/styles.css`, `tests/test_webui.py`,
`docs/UI_ROUTE_ACTION_MATRIX.md`, `docs/UI_REBUILD_PLAN.md`,
`docs/assets/ui-concepts/README.md` and
`docs/assets/ui-concepts/renders/royal-command-new-arena.png`, the updated arena
render, destroy confirmation, Git intake, OCI intake, PoC workspace, findings
finding confirmation and evidence workspace renders.

**Verification:** Focused WebUI tests, Ruff, TypeScript/Prettier, Vite build and
the reproducible multi-stage WebUI Docker build passed. `make release-check`
passed on Python 3.11.14 against this slice: Ruff and source Bandit clean
(zero medium/high), SQLite 954 passed/4 skipped/6 deselected, PostgreSQL 958
passed/6 deselected, and migration/API/UI/gateway readiness smoke passed.
Headless Chromium
inspected the launch page at 1440, 390 and 320 px without page overflow. With
local fixture responses, scenario, Git and OCI launch submissions reached the
arena workspace. The PoC view was inspected at 1440, 390 and 320 px without
page overflow; fixture-backed submit and result inspection worked. Findings
and evidence were inspected at 1440, 390 and 320 px without page overflow;
the evidence render uses local fixture records. This does
not establish a real Docker-local deploy or a
complete end-to-end research journey. Accessibility audit remains open.

**Unresolved risks / next step:** Migrate source-bundle intake and HTTP tools;
verify PoC and finding paths with a real Docker-local
arena, then complete action/state parity and verify a
real Docker-local run before changing the default console.

## 2026-09-27 — Royal Command React console, opt-in first slice

**Outcome:** Selected Royal Command after operator review and started the real
same-origin React/TypeScript/Vite console at `/console`. Research, Benchmark and
Cyber Range dashboards read narrow authenticated Flask projections; a new
`/console/arena/<id>` overview reads real arena state, budget, nodes, events,
finding and PoC counts. The arena overview can stop or resume the research
gate through a CSRF-protected BFF request and a named confirmation dialog;
the service still decides whether the transition is permitted. Benchmark now
configures and submits matched comparisons through a CSRF-protected BFF action;
`/console/evaluations/<id>`
reads paired differences, challenge attribution, uncertainty and trial links.
The interface uses larger operating cards, responsive
navigation and a persisted day/night preference. Rune-like SVG marks identify
the three workspaces; the arena Fuzz control is disabled because NV-12 remains
planned. Existing Flask actions remain linked while parity is migrated.
ADR-0017 records the rendering change and preserves ADR-0012 service boundaries.
The generated first-pass matrix inventories Flask route/method operations.

**Files:** `cyber-range/webui/frontend/`, `cyber-range/webui/app.py`,
`cyber-range/webui/templates/console.html`, WebUI Dockerfile/.dockerignore,
`.gitignore`, `tests/test_webui.py`, `docs/adr/0017-react-operator-console-rendering.md`,
`docs/UI_ROUTE_ACTION_MATRIX.md`, `scripts/inventory-webui-routes.py`, the
Royal Command prototype and `docs/UI_REBUILD_PLAN.md`.

**Verification:** TypeScript/Vite build passed locally. A clean multi-stage
WebUI Docker build reproduced the assets. Focused WebUI tests passed, including
session protection, backend failure and projection redaction. Ruff and
`git diff --check` passed. Headless Chromium inspected loaded fixture-backed
Research, Benchmark, Cyber Range and arena views at 1440, 1024, 390 and 320 px,
plus evaluation detail and comparison setup at 1440, 390 and 320 px; no
horizontal overflow was found, and a night-theme render was inspected. The
fixture-backed comparison form submitted and opened the result route. These
screenshots used fixture data and are visual evidence only. No authenticated
Docker-local research journey, accessibility audit,
researcher observation or pinned `make release-check` was run for this UI slice.

**Unresolved risks / next step:** `/console` is opt-in. Creation, live tools,
PoC, findings, build/challenge/suite registration, broader Cyber Range lifecycle, SSE and
shared resource editing still use legacy pages. Finish the per-action/state
matrix, migrate complete journeys, test session expiry/CSRF/reconnect, then run
the required live and release gates before a default switch. NV06-R1, NV07-R1
and INFRA-R1 remain open.

## 2026-09-27 — New Royal Research dashboard concepts for review

**Outcome:** Replaced the visual direction of the rejected Atelier/Instrument
prototypes with two new clickable Research dashboards: Royal Command and Forge
Canvas. Both use a light surface with Nidavellir's ink, violet and gold identity.
They present an active session, pending finding, evidence and session history,
and expose a local import → PoC → finding → archived-record demonstration.
These are visual prototypes with declared mock data; no backend route, product
feature, React shell or roadmap checklist item changed.

**Files:** the new HTML, CSS, JavaScript and README in
docs/assets/ui-concepts/, plus this journal. Earlier prototype files are
retained as rejected comparison material.

**Verification:** Headless Firefox renders were inspected at 1440, 390 and
320 px for the dashboard concepts, plus desktop PoC and finding screens.
JavaScript syntax, HTML IDs/routes and documentation whitespace checks passed.
No authenticated browser journey, accessibility audit, user task observation,
backend test, Docker-local gate or pinned release gate was run for these
documentation-only prototypes.

**Unresolved risks / next step:** Operator visual feedback must choose or revise
one direction. The phase-0 route/action matrix, three full journeys, measured
baseline, new rendering ADR and typed BFF contracts remain open. NV06-R1,
NV07-R1 and INFRA-R1 are unchanged.

## 2026-09-27 — Console rebuild implementation guide

**Outcome:** Reworked the console plan around Research → Benchmark → Cyber Range,
with a light default theme, direct action labels, current capability states,
complete workspace journeys, shared resources, migration phases and UI parity
criteria. The plan requires a new ADR superseding only ADR-0012's Flask/Jinja
rendering choice. This is documentation only; no React UI, product feature or
roadmap checklist item was completed.

**Files:** `docs/UI_REBUILD_PLAN.md` and this journal.

**Verification:** Cross-checked README, ROADMAP, TODO, ISSUES, relevant ADRs,
current Flask routes and recent journal evidence; checked documentation diff
for whitespace. No application tests or live gates were run for this edit.

**Unresolved risks / next step:** NV06-R1, NV07-R1, INFRA-R1 and NV-09 remain
open. Inventory every current route/action, review two Research concepts, then
write the replacement rendering ADR and typed BFF contracts before frontend
implementation.

## 2026-09-27 — NV-10 encrypted research and evaluation recovery

**Outcome:** Implemented an offline, versioned AES-GCM recovery bundle for all
research/evaluation tables and events plus persistent scenarios, target inputs,
evidence, HTTP transactions, validation observations, runs, keys and traces.
The bundle carries the Fernet key needed to decrypt historical records; restore
writes it to a mode-0600 recovery environment file. An aggregate-only sharing
report is generated through a separate command. Restore authenticates the
bundle and validates schema/revision, file and content-address digests, and
record/evidence references before writing to an empty installation. It rolls
back copied files if database installation fails and advances PostgreSQL's
event sequence after importing explicit audit IDs. Deployment record deletion
and bulk purge retain research/evaluation records with evidence.

**Files:** `recovery.py`, `database.py`, `api.py`, `tests/test_recovery.py`,
`scripts/verify-nv10-live.py`, `docker-compose.nv10.yml`, `docker-compose.yml`, `Makefile`,
`docs/OPERATIONS.md`, `README.md`, `ROADMAP.md`, `TODO.md`, `ISSUES.md`, and
NV-10/NV-09 verification manifests. Existing edits to ROADMAP, TODO and this
journal were preserved.

**Verification:** The isolated Docker-local gate produced a synthetic SPA
evaluation, destroyed all arenas, encrypted a full backup, generated a
redacted share report, restored into a new PostgreSQL database and empty
volumes, decrypted/read the historical result and validation observation,
then reran the restored fixture. Both runs produced three matched pairs,
zero infrastructure-failed pairs and a verified difference of -1; all
arena-labelled resources and NV-10 Compose containers, networks and volumes
were absent after teardown. Evidence:
`docs/verification/nv10-live-2026-09-27-fa97b910.json` and
`docs/verification/nv10-gates-2026-09-27.json`. Seven focused recovery tests
cover decryptable round trip, redaction, tamper rejection, schema rejection,
missing evidence, retention and rollback after a database-install error.
The final pinned `make release-check` passed: 941 SQLite tests (four skips),
945 PostgreSQL tests, six integration deselections per suite, Ruff clean,
Bandit zero medium/high, and release smoke ready.

**Unresolved risks / next step:** Recovery requires an offline maintenance
window; concurrent writers cannot be made consistent across PostgreSQL and
filesystem volumes. OCI image bytes are not in the bundle, so replay on a
different Docker host requires the pinned image or immutable build inputs.
NV-09 and the model-driven evaluation risk remain open. Next, use the recovery
procedure on a scheduled maintenance window and retain an independent copy of
the encrypted bundle and its passphrase in separate custody.

## 2026-09-27 — NV07-R1 smoke outcome and Claude Code MCP verification

**Outcome:** The one authorized Gemini durable smoke was submitted against the
isolated, current PostgreSQL stack. Its evaluation completed, but the only trial
failed as `infrastructure_failure` with a generic MCP `ExceptionGroup`; no
provider usage, transcript or verdict was recorded. The stack used an ephemeral
encryption key, and teardown left zero labelled Docker resources. No retry was
made. Trial error handling now unwraps nested task-group failures while storing
only an allowlisted status message or exception class, without provider bodies,
prompts or credentials.

At the operator's direction, Claude Code Haiku then participated directly over
Nidavellir MCP in the synthetic NV-06 authorization arena. In five turns it
read B's synthetic object as A and submitted one finding. The independent
`authorization_effect` validator confirmed `unauthorized_read`; score was 1/1,
and the export remained available after arena teardown. Claude Code reported
$0.0477513 and token usage. This verifies direct Claude Code MCP access, not a
successful durable `model-mcp/v1` trial; NV07-R1 remains open.

The NV-09 live gate was rerun after the API request models began rejecting
unknown budget fields: three matched pairs, three confirmed and three refuted
verdicts, zero infrastructure failures and zero residual labelled resources.
The recorded verified difference is -1 for the synthetic SPA challenge. NV-09
remains open for a real Bughunt agentic-client handoff and operator workflow
measurement.

**Files:** `experiments.py`, `tests/test_nv07_experiments.py`,
`docker-compose.nv07.yml`, `docs/API.md`, the NV07 setup, smoke and MCP records,
the latest NV-09 manifest, and the Claude MCP preparation/finalization scripts.

**Verification:** The NV-09 evidence is
`docs/verification/nv09-live-2026-09-27-b97417df.json`; the direct MCP evidence
is `docs/verification/nv07-claude-mcp-2026-09-27-58bcfa5a.json`; the failed
durable smoke is `docs/verification/nv07-r1-smoke-2026-09-27-e513c3d9.json`.
The final `make release-check` passed with Ruff, zero medium/high Bandit,
release smoke, 934 SQLite passes (four skips) and 938 PostgreSQL passes;
six integration tests were deselected in each suite.

**Unresolved risks / next step:** The Gemini trial's underlying leaf cause is
unknown because its worker stack was already torn down; provider usage and
billing are also unknown. The safer diagnostic passed the pinned release gate.
NV07-R1 still requires a successful model-driven durable trial
and a repeated suite showing variability and token/cost attribution. NV-09
remains calibration evidence only and has no maintained Bughunt adapter.

## 2026-09-28 — NV-09 scope clarified against current bughunt state

**Outcome:** No code change. Gianluca flagged that bughunt is mostly deterministic
pipelines (BH-01/03/04 — enumeration/baseline/worker/backup); the only agentic
component is Hermes/Claude Code + MCP driving active testing against target webapps.
Cross-checked with `@bughuntmanager` against bughunt's current authoritative
PLAN.md/TODO.md (checkpoint 2026-09-15) — an earlier grep had hit a stale copy under
`dev/history/2026-09-10-before-agent-driven/TODO.md`. Confirmed: BH-13/BH-14B/BH-15
("Hermes execution/evaluation") name the agentic layer only. Bughunt D021 states the
deterministic pipelines run independent of Nidavellir/Hermes by design; D017 states the
BH-13/NV-09 manifest exchanges synthetic scenario/target + evidence, never live campaign
credentials. Bughunt's 2026-09-10 proposal names the first concrete vertical slice: one
synthetic SPA, two accounts, one owned object, one cross-account comparison, one restart;
broad autonomous crawling explicitly excluded from that slice.

**Files:** `TODO.md` (NV-09 entry), `ROADMAP.md` (BH-13/NV-09 integration paragraph) —
scope clarification only, no change to dependencies or accept criteria.

**Verification:** Confirmed via direct message from `@bughuntmanager`, citing bughunt
D017, D021, TODO.md:178 and the 2026-09-10 agent-workflow proposal. Not independently
re-read against the bughunt repo from this session.

**Unresolved risks / next step:** NV-09 itself is still not started (depends on NV-02-06,
first NV-08 fixture, NV-07). Next concrete step unchanged: pick the first vertical-slice
fixture (bughunt's synthetic-SPA slice is the named candidate) and scope the joint
manifest fields before any implementation work.

## 2026-09-27 — Synthetic NV-09 SPA gate and NV07-R1 model smoke preparation

**Outcome:** Added a synthetic, client-rendered two-account SPA and the versioned
BH-13/NV-09 agentic test/evidence manifest. A scripted MCP browser/HTTP workflow
ran three matched baseline/candidate pairs; only the cross-account request path
changed. The independent target-local authorization validator confirmed all
three vulnerable-path findings, refuted all three denied-path claims, and
attributed the -1 verified regression to the SPA challenge with zero
infrastructure-failed pairs. Evidence remained readable after teardown; all
labelled arena resources were reclaimed. This establishes a useful harness
regression, but not an actual Bughunt client integration or a held-out result.

Added `model-mcp/v1` to durable evaluations using the operator's pinned model
connection and the scoped gateway. It bounds model turns/output requests and
records provider-reported usage, termination and trial trace. A separate
operator-only single-trial calibration endpoint prevents a first smoke from
silently launching the existing paired multi-seed suite. Only mocked provider
responses were used. The running main stack has a standby `gemini-2.5-flash`
connection but an older model-connection schema, so no model run is authorized
or ready. NV07-R1 remains open.

**Files:** `cyber-range/fixtures/nv09-spa/`,
`cyber-range/services/scenario-orchestrator/{api,database,experiments,eval_model_driver}.py`,
`scripts/verify-nv09-live.py`, `Makefile`, `tests/test_nv09_slice.py`,
`tests/test_eval_model_driver.py`, `tests/test_nv07_experiments.py`,
`docs/verification/nv09-live-2026-09-27-{aed88ffd,b17ac7a2}.json`,
`docs/verification/nv09-assessment-2026-09-27.md`,
`docs/verification/nv07-r1-preflight-2026-09-27.md`, and this journal.

**Verification:** Final `make verify-nv09-live` passed: six trials, three matched
pairs, zero infrastructure-failed pairs, three confirmed/three refuted verdicts,
zero labelled resources. The final manifest is
`docs/verification/nv09-live-2026-09-27-b17ac7a2.json` and records a 19.71 s
setup stage. The pinned release gate passed with Ruff, zero medium/high Bandit,
readiness smoke, 933 SQLite passes (four skips) and 937 PostgreSQL passes;
six integration tests were deselected in each suite. No model API was called.

**Unresolved risks / next step:** NV-09 stays open because the Bughunt repository
was read-only and no Bughunt agentic client consumed the manifest or showed a
measured operator benefit. Given the operator's emphasis on self-hosted 0-day
research, retain this as a harness regression before considering a Bughunt
adapter. NV07-R1 requires an aligned main-stack schema, a verified billing/usage
connection, specific permission for one live smoke, then a repeated model-driven
suite before closure. NV06-R1 and INFRA-R1 remain open.

## 2026-09-27 — Evaluation UI concept and mock engagement walkthrough

**Outcome:** Corrected stale "foundation" navigation on the working Evaluations and
Agent builds pages. Evaluations now presents a four-step operator journey with
registry summaries, prerequisites, styled forms, honest calibration/model-driver
boundaries and readable comparison details. Agent builds has a real registry view;
Home counts durable evaluations instead of advertising them as future work.
Created one operator-led, four-hour calibration engagement using the existing
`container_web_pentest` scenario and explicit `mock` provider for UI exploration.
The workspace labels every mock address/output as simulated and does not link
to a simulated target URL. No real victim or agent/model execution was used.

**Files:** `cyber-range/webui/{app.py,templates/base.html,templates/evaluations.html,templates/evaluation_detail.html,templates/agent_builds.html,templates/arena_detail.html,templates/overview.html,static/css/app.css}`,
`tests/test_webui.py`, and `docs/verification/ui-concept-2026-09-27.json`.

**Verification:** `make release-check` passed on pinned Python 3.11.14: Ruff,
Bandit (zero medium/high), release smoke, 924 SQLite passed (four skipped) and
928 PostgreSQL passed (six integration tests deselected in each). The rebuilt
webui returned 200 for Home, Evaluations, Agent builds, Engagements and the
demo workspace; guided anchors, demo listing, mock warning and suppression
of the fake-target link were checked live. The demo had zero labelled Docker
containers, networks and volumes. See the verification JSON for its ID and
expiry.

**Unresolved risks / next step:** The three true foundation destinations
(Targets registry, Providers & capacity, Security) remain planned; this is a
concept polish, not a full console rebuild. The demo is simulated and cannot
validate a vulnerability. NV07-R1, NV06-R1 and INFRA-R1 remain open. Next
product work is NV-09; the user may first review the UI concept and identify
which flow needs redesign.

## 2026-09-26 — Final NV-08 gates and collision-safe live evidence

**Outcome:** Final NV-06, NV-07, NV-07 recovery and NV-08 Docker-local gates
passed after the last product change. Their verifiers now create unique,
date-named evidence files exclusively, never overwriting committed records.
The final NV-08 rerun again completed 20 trials in ten matched pairs with zero
infrastructure-failed pairs and zero labelled resources. The pooled verified
difference was -0.5, bootstrap 95% [-0.8, -0.2], `supported`; grant and
authorization differences were -1 and 0 respectively, each `degenerate`.
These are calibration results only.

**Files:** `scripts/verify-nv06-live.py`, `scripts/verify-nv07-live.py`,
`scripts/verify-nv07-recovery-live.py`, `ISSUES.md` and final gate evidence in
`docs/verification/`.

**Verification:** Pinned `make release-check` passed: Ruff, Bandit, release
smoke, 921 SQLite passed (four skipped), 925 PostgreSQL passed; six integration
tests deselected in each suite. `make verify-nv06-live`,
`make verify-nv07-live`, `make verify-nv07-recovery-live` and
`make verify-nv08-live` all passed. See
`docs/verification/nv08-final-gates-2026-09-26.json` for the exact paths.

**Unresolved risks / next step:** NV07-R1 remains open: no Nidavellir model
connection is configured for durable evaluations, and no Claude subscription
run was invoked. NV06-R1 still needs a non-synthetic target; INFRA-R1 belongs
to NV-13. NV-09 is next in the delivery order. A model-driven NV07-R1 run
requires its own setup and explicit permission for each live invocation.

## 2026-09-26 — Complete NV-08 two-class calibration regression gate

**Outcome:** A suite now compares authorization and single-use-grant business
logic by challenge as well as in aggregate. A good scripted build and a build
with only the grant redemption step regressed ran on five seeds each. All 20
trials completed, forming ten observed-state-matched pairs. The regression
affected grants only: candidate-minus-baseline verified difference -1 on
grants and 0 on authorization. The pooled mean was -0.5 with bootstrap 95%
[-0.8, -0.2] and `interval_status=supported`; the constant per-class verified
intervals are `degenerate`. Both classes remain calibration, not capability
evidence. All archived scores, exports, and business observation/control
digests remained readable after teardown; zero labelled resources remained.
NV-08 acceptance and NV07-R2 are closed. NV06-R1 remains open for a
non-synthetic target.

**Files:** `experiments.py`, evaluation detail template,
`scripts/verify-nv08-live.py`, `Makefile`, `tests/test_nv07_experiments.py`,
`docs/API.md`, `TODO.md`, `ISSUES.md`, `ROADMAP.md`, `README.md`, `AGENTS.md`
and live evidence.

**Verification:** `make release-check` passed on pinned Python 3.11.14:
Ruff clean, Bandit zero medium/high, 921 SQLite passed (four skipped), 925
PostgreSQL passed, six integration deselections each, smoke passed.
`make verify-nv08-live` passed with 20 completed trials, ten matched pairs,
zero infrastructure failures, 20 retained business observation/control digests
and zero labelled resources across 22 arenas. Evidence:
`docs/verification/nv08-live-2026-09-26-bb79440f.json`.

**Unresolved risks / next step:** NV07-R1 still lacks a model-driven durable
suite; every live subscription invocation needs separate operator permission.
NV06-R1 needs non-synthetic validation and INFRA-R1 remains Docker-local only.
Next is the opt-in model driver, followed by NV-09.

## 2026-09-26 — NV-08 steps 1–2: versioned authorization and grant challenge

**Outcome:** The NV-06 authorization fixture is a versioned calibration library
entry with pinned accounts, seed, private truth, validator identity and reset
strategy. Challenge creation requires an explicit leakage label; trial exports
and comparisons carry it. A second, synthetic single-use-grant challenge now
has an independent target-ledger validator with a healthy redemption control
and the NV-06 four-way verdict. I chose business logic because the target's
ledger gives a direct, resettable state effect distinct from an object read;
the `dvsn` portfolio remains a later integration candidate, not non-synthetic
proof. No model subscription evaluation has run.

**Files:** `cyber-range/fixtures/nv06-authz/`, `cyber-range/fixtures/nv08-grants/`,
`api.py`, `validators.py`, `experiments.py`, `database.py`, evaluation console,
`docs/API.md`, `tests/test_nv07_experiments.py`,
`tests/test_nv08_grant_validation.py`, and step gate JSON.

**Verification:** `make release-check` passed after each step on pinned Python
3.11.14. Step 1: 916 SQLite passed, four skipped, 920 PostgreSQL passed.
Step 2: 920 SQLite passed, four skipped, 924 PostgreSQL passed. Each gate
excluded six integration tests, with Ruff, source-only Bandit and release
smoke passing. Evidence: `docs/verification/nv08-step1-gates-2026-09-26.json`
and `nv08-step2-gates-2026-09-26.json`. A live two-class run remains pending.

**Unresolved risks / next step:** NV07-R2 and NV06-R1 remain open until live
two-class evidence exists; NV06-R1 additionally requires a non-synthetic target.
NV07-R1 remains open; subscription-backed live evaluation requires explicit
permission for each invocation. Next is the combined regression gate.

## 2026-09-26 — Close NV07-R4, NV07-R5 and VERIF-R1; evaluation heartbeat

**Outcome:** Three open risks are closed and the one-hour evaluation ceiling
is gone. Trial claim/finish now refresh `Evaluation.updated_at`, so stale
recovery means "no trial progress for 70 minutes" rather than "started over 70
minutes ago". `tasks.enqueue_evaluation` sizes the Celery time limit from the
suite (trials × (deadline + 600 s)), used by both the API and the reaper
requeue. A soft time limit closes the remaining trials as
`infrastructure_failure/time_limit` instead of leaving them for recovery.
The unused `terminalize_stale_eval_trials` became
`terminalize_unfinished_eval_trials`. A new live gate,
`make verify-nv07-recovery-live`, SIGKILLs the worker mid-trial and proves the
reaper terminalizes it. The only simulated element is the 70 minutes of
silence (heartbeat backdated), and the evidence file says so. NV-02–07 live
gates were rerun. The NV-03 and NV-06 verifiers now write date-named evidence;
the NV-03 run had overwritten its committed 2026-09-22 file, which was restored
from git. No scoring, validation or verdict behaviour changed. NV-08 is still
not started.

**Files:** `database.py`, `experiments.py`, `tasks.py`, `api.py`,
`tests/test_nv07_experiments.py`, `scripts/verify-nv07-recovery-live.py`,
`scripts/verify-nv07-live.py` (`prepare()` extracted),
`scripts/verify-nv03-live.py`, `scripts/verify-nv06-live.py`, `Makefile`,
`docs/API.md`, `AGENTS.md`, `ISSUES.md`, verification JSON and this entry.

**Verification:** `make release-check` passed on Python 3.11.14: Ruff clean,
Bandit zero medium/high, 913 SQLite passed (four PostgreSQL-only skips), 917
PostgreSQL passed, six integration deselections each, smoke passed.
`make verify-nv07-recovery-live` passed: trial `dc22c2f3-…` killed while
holding arena `c11c1282-…`, left alone while fresh, terminalized as
`infrastructure_failure/worker_interrupted`, arena reclaimed, evaluation
unchanged after worker restart, 0 matched / 3 infrastructure-failed pairs,
zero labelled resources. `verify-nv02-live` … `verify-nv07-live` all passed
with zero labelled resources (NV-07: three matched pairs, mean 1.0,
`degenerate`). The full host Python 3.14.7 suite ran to completion (913
passed) with a 60 s faulthandler watchdog. That is signal only. Evidence:
`docs/verification/nv07-hardening-gates-2026-09-26.json` and the
`*-2026-09-26.json` files.

**Unresolved risks / next step:** Open risks are NV07-R1 (no model-driven
build), NV07-R2 and NV06-R1 (one calibration challenge class) and INFRA-R1
(Docker-local only). The live kill hit the first trial, so preservation of
completed trials under recovery is shown by the unit test only. Next is NV-08.

## 2026-09-26 — NV-07 follow-ups: recovery coverage (R5) and interval labels (R3)

**Outcome:** Closed NV07-R3 and narrowed NV07-R5. `experiments.compare` now
adds `distinct_values` and `interval_status` to every per-metric difference:
`degenerate` when all matched differences are identical (the `[1.0, 1.0]`
case), `insufficient_pairs` below `MIN_INTERVAL_PAIRS = 5`, `supported`
otherwise, `no_pairs` when nothing matched. The bootstrap numbers are still
emitted; the label says whether they carry information. The console prints the
status next to each interval. New tests drive `recover_stale_evaluations`,
`queued_evaluations_before` and `reap_labs` over stale `running`/`queued`
rows: unfinished trials become `infrastructure_failure/worker_interrupted`,
completed results survive, a lost worker's late finish or claim is rejected,
recovery is idempotent, fresh/queued/complete rows are left alone and a
duplicate delivery of a running evaluation is skipped. No scoring, validation
or trial-execution behaviour changed. NV-08 was not started in this session.

**Files:** `experiments.py`, `evaluation_detail.html`, `tests/test_nv07_experiments.py`,
`scripts/verify-nv07-live.py` (asserts the degenerate label; `NV07_EVIDENCE`
selects the output file), `docs/API.md`, `ISSUES.md`, the verification JSON and
this entry.

**Verification:** First `make release-check` failed: three reaper tests reached
Redis because the new tests left backdated `queued` evaluations in the shared
test DB. A fixture now closes them. The rerun passed on Python 3.11.14: Ruff
0.6.9 clean, Bandit 1.9.4 zero medium/high, 910 SQLite passed (four
PostgreSQL-only skips), 914 PostgreSQL passed, six integration deselections
each, clean Alembic and API/console/MCP smoke. `make verify-nv07-live` (run
with `NV07_EVIDENCE=nv07-followups-live-2026-09-25.json`) passed: evaluation
`c757ebc8-…`, three matched pairs, verified mean 1.0 labelled `degenerate`,
latency `insufficient_pairs`, cost `no_pairs`, zero labelled resources across
seven arenas. Evidence: `docs/verification/nv07-followups-gates-2026-09-25.json`
and `nv07-followups-live-2026-09-25.json`.

**Unresolved risks / next step:** NV07-R5 stays open until a live worker kill
mid-trial is shown to be terminalized by the reaper. Recovery keys on
`Evaluation.updated_at`, which is safe only while one evaluation fits inside
the 61-minute task limit; longer NV-08 suites need a heartbeat or a split task.
NV07-R4 (NV-02–06 live regressions) is still not rerun. Next is NV-08.

## 2026-09-25 — Complete NV-07 durable paired evaluations

**Outcome:** NV-07 is complete on Docker-local. The platform now holds durable,
versioned Agent build, Challenge, Suite, Evaluation, Run and Trial records and
compares a baseline against a candidate build over repeated matched trials.
A build pins its scripted MCP plan behind a content-addressed digest over name,
version and config; a challenge pins an active, reset-eligible Docker-local
source arena's recipe digest and validator version; a suite pins seeds, action
cap and deadline. Each trial deploys its own arena from the pinned recipe,
re-checks that the observed starting state matches the pinned source, applies
the suite budget/deadline, plays the plan through the stance-scoped gateway and
destroys the arena. Trials are claimed atomically, so a worker restart cannot
double-run one; the reaper recovers stale claims and requeues stranded
evaluations. All five endpoints and both console pages are operator-only;
participants reach the arena only through the gateway and never see an
evaluation record. Scoring, validation and NV-06 verdict behaviour are
unchanged — no product logic was modified to reach acceptance.

The comparison pairs trials by challenge and seed and counts a pair only when
both sides completed from the same observed-state digest. Candidate-minus-
baseline differences for verified outcome, false claims, requests, latency and
available cost carry a seeded bootstrap 95% interval, and pairs where either
side ended in `infrastructure_failure` are counted separately rather than
charged to the agent.

The first live run failed acceptance with both sides at verified 0. The cause
was in the verifier, not the product: its scripted plan sent a hyphenated
`X-Request-ID`, which the fixture (`isalnum`) and the authorization validator
(`[A-Za-z0-9]{1,64}`) both reject, so no action linked and every finding
resolved to `inconclusive/missing_action`. The verifier now sends an
alphanumeric ID, matching the NV-06 contract, and also tears its isolated
Compose project down before starting.

**Files:** `experiments.py`, durable models and Alembic `0009_evaluations`,
database CRUD/claim/recovery, operator-only `/agent-builds`, `/eval-challenges`,
`/eval-suites`, `/evaluations` and `/evaluations/{id}`, the `run_evaluation`
worker task and reaper recovery, Flask evaluation and agent-build pages,
`tests/test_nv07_experiments.py`, `tests/test_webui.py`,
`scripts/verify-nv07-live.py`, `docker-compose.nv07.yml`, the `verify-nv07-live`
Makefile target, `docs/API.md`, README, ROADMAP, TODO, the verification JSON and
this journal entry.

**Verification:** `make release-check` passed on Python 3.11.14: Ruff 0.6.9
clean, Bandit 1.9.4 with zero medium/high findings, 903 SQLite tests passed
(four PostgreSQL-only skips), 907 PostgreSQL tests passed, six declared
integration deselections on each backend, and clean Alembic plus
API/console/MCP readiness smoke. `make verify-nv07-live` passed after the fix:
six trials completed, three matched pairs, candidate-minus-baseline verified
difference of exactly 1 on every pair (mean 1.0, range [1, 1], bootstrap 95%
[1.0, 1.0]), false-claim difference -1.0, zero infrastructure-failed pairs,
score and eval export still readable for all six arenas after teardown, and
zero labelled containers, images, networks and volumes across all seven
arenas. The fixture image was
`sha256:cb5ba133686e30b5bab036d4431a5f6d04b27c1341a90f8f42be5b02f31f9b34`.
Results and IDs are in `docs/verification/nv07-live-2026-09-25.json` and
`nv07-gates-2026-09-25.json`. `git diff --check` passed. Nothing was pushed.

**Unresolved risks / next step:** The paired comparison is proven with one
deterministic scripted-MCP driver against one calibration challenge; a real
BYO model-driven build and a second challenge class are untested here, and the
bootstrap interval over three seeds is a reporting device, not a strong
statistical claim. NV-02–06 live regressions were not rerun after this change,
which touches only new NV-07 code paths and the NV-07 verifier. These and the
carried provider/verification gaps are now tracked as a standing register in
`ISSUES.md`, linked from the AGENTS.md reading order. Next is NV-08's
dependable challenge library; ROADMAP's "Next to build" block states its
three concrete deliverables.

## 2026-09-24 — Complete NV-06 independent authorization validation

**Outcome:** NV-06 is complete on Docker-local. Froze the five-case acceptance
matrix before changing validation/scoring and built a resettable, image-pinned
synthetic A/B authorization target first. The platform now links a participant's
recorded HTTP action to target-local effect read-back and a B-to-B healthy
control. An append-only `nidavellir/validation-verdict/v1` finding event cites
the pinned recipe/target, action, effect/control digests, validator version,
timestamp, four-way verdict and reason code. Observation files are arena-scoped,
content-addressed and integrity-checked; operators can review them after
teardown. REST/MCP agent acknowledgements remain neutral and agent events hide
private match/verdict and manual review. No migration was needed.

The marker validator now requires manifest-owned truth; passive crash credit
requires a linked same-node action within 120 seconds. Benchmark headline
success uses automatically confirmed points, while claim coverage and
digest-citing manual judgment remain separate. Discovery displays unlinked
faults without granting headline success. The console shows verdict/reason and
action/effect/control links. Code review caught and fixed a projection in which
manual confirmation displaced automatic proof; the final tests and gates ran
after that fix. ADR-0009 records the amended scoring contract.

**Files:** Authorization fixture and `docker-compose.nv06.yml`; scenario
schema, validator, evidence store, finding API and scorer; console findings,
score and evidence views; `scripts/verify-nv06-live.py`, focused tests,
`docs/API.md`, ADR-0009, acceptance/gate JSON, README, ROADMAP, TODO and this
journal. `docs/UI_REBUILD_PLAN.md` and prior journal entries are preserved.

**Verification:** Final `make release-check` passed on Python 3.11.14:
Ruff 0.6.9 clean, Bandit 1.9.4 with zero medium/high findings, 901 SQLite
tests passed (four PostgreSQL-only skips), 905 PostgreSQL tests passed, six
declared integration deselections on each backend, and clean Alembic plus
API/console/MCP readiness smoke. Final `make verify-nv06-live` passed:
positive A-to-B access `confirmed/unauthorized_read`; denied path
`refuted/access_denied`; B-to-B control `control_ok`; unsupported claim
`inconclusive/missing_action`; stopped target
`infrastructure_failure/probe_failed`. It also proved MCP neutral ack,
agent truth denial/redaction, reset observed-state equivalence, operator
console and transaction/effect/score review after teardown, and zero labeled
containers, images, networks and volumes across three arenas. The fixture image
was `sha256:cb5ba133686e30b5bab036d4431a5f6d04b27c1341a90f8f42be5b02f31f9b34`;
the final positive recipe was
`sha256:521be6a30198bb99adb95fe801e8e66b18ca8176c7134491550b844abf27f378`.

After the final product change, NV-02 reset/retained-evidence (five arenas),
NV-03 confined PoC (three), NV-04 durable budget/stop (two), and NV-05 scoped
forward (four) live regressions passed with zero final labeled resources.
The first NV-04 rerun hit its three-second expiry deadline during worker
shutdown, returning the expected 409 before the fixture could enqueue its
job; its failure cleanup left zero labeled resources. The verifier now stops
the worker before starting a 15-second deadline, and the next run passed.
Exact results and IDs are in `docs/verification/nv06-gates-2026-09-24.json`,
`nv06-live-2026-09-24.json`, `nv02-regression-2026-09-24.json`, and the
refreshed NV-03/04/05 live JSON. Final documentation/JSON validation and
`git diff --check` passed. Nothing was pushed.

**Unresolved risks / next step:** This is one calibration fixture and one
class-specific validator, not a held-out challenge library or a live cloud/VM
claim. Legacy validator evidence remains at its existing contract. Durable
paired Agent build/Challenge/Evaluation/Run/Trial records, repeated
comparisons and infrastructure-failure accounting are NV-07.

## 2026-09-23 — P1 vertical-result handoff after NV-05 checkpoint

**Outcome:** Committed the completed NV-05 implementation and passing evidence
locally as `7df304a`, without pushing. Replaced the completed NV-05 handoff in
`tmp-implementationPlan.md` with a planning-only P1 sequence. NV-06 starts
with one independently verified authorization result and positive, negative,
healthy and failure controls; NV-07–10 generalize that evidence into paired
trials, a small challenge, synthetic Bughunt usefulness proof and recovery.
NV-06–10 remain unchecked. Prior journal history and `docs/UI_REBUILD_PLAN.md`
are unchanged.

**Files / verification:** This planning checkpoint changes only the handoff
and this journal entry. The NV-05 commit contains the implementation and saved
gate evidence listed below. No product code or full test gate ran for this
plan; reviewed the existing validator, score, finding and event seams and ran
`git diff --check` on the planning changes.

**Risks / next step:** The current marker validator can use a caller-supplied
marker, crash confirmation can lack action linkage, and benchmark `found`
points can reflect a claim before effect confirmation. The next builder should
freeze the NV-06 acceptance matrix and construct its fixture before changing
the API or scorer. No P1 completion is claimed.

## 2026-09-23 — Complete NV-05 scoped research access and runtime capabilities

**Outcome:** NV-05 is complete on Docker-local. Scenario nodes now declare named
internal TCP services separately from host-published ports; the immutable
lifecycle recipe and equivalence digest retain them. An attacker binding or
operator can create an idempotent, expiring, single-stream lease to one service
from a selected foothold segment. The worker resolves the actual owned target
container, verifies the exact shared internal network, and owns a labeled,
resource-limited fixed-destination relay. An independently authenticated
WebSocket carries bytes through bounded Redis frames. Creation and stream
opening each spend durable NV-04 actions. Revoke, expiry, binding pause/revoke,
stop, reset, teardown and worker-loss recovery close and reclaim access.
ADR-0016 is accepted; this is a TCP relay, not SSH. A versioned, principal-
filtered capability manifest is available through REST, attacker and operator
MCP discovery, and the current Flask workspace, with CSRF-protected lease
controls.

**Files:** Scenario schema and lifecycle projection; migration `0008`, lease
model/database methods, API routes and WebSocket, worker task, Docker provider
and trusted relay script; gateway client/tools, Flask workspace and local
loopback client; two-segment fixture, isolated Compose/live verifier, focused
PostgreSQL race tests; `docs/API.md`, ADR-0016, TODO, ROADMAP, README and this
journal. `docs/UI_REBUILD_PLAN.md` and prior journal entries remain intact.

**Verification:** Final `make release-check` passed on pinned Python 3.11.14:
Ruff 0.6.9 clean, Bandit 1.9.4 with zero medium/high findings, 891 SQLite
tests passed (four PostgreSQL-only skips), 895 PostgreSQL tests passed, six
declared integration deselections on each backend, and clean Alembic plus
API/console/MCP readiness smoke. PostgreSQL tests raced lease create/claim,
revoke/connect and stop/helper-start. `make verify-nv05-live` passed: internal
fixture bytes via the declared foothold segment, wrong destination and stance
denial, filtered manifest, MCP and CSRF console control, loopback client,
mock-provider unsupported state, active revoke and expiry with reconnect
denial, binding revocation, arena and persistent system stop, stop/stream race,
killed-worker recovery, replacement reset and zero final labeled
containers/networks/volumes. Its active revoke closed in 0.34 s.
The NV-02, NV-03 and NV-04 Docker live regressions passed afterward, each with
zero final labeled resources. Evidence: `docs/verification/nv05-gates-2026-09-23.json`,
`nv05-live-2026-09-23.json`, and refreshed NV-03/NV-04 live JSON files.
`git diff --check` passed.

**Unresolved risks / next step:** Only Docker-local has live forward support;
cloud/VM providers explicitly refuse it. TCP is fixed destination and limited
to one stream, 1 MiB each direction, 90 seconds and 15 idle seconds. Model
token/cost hard caps remain unsupported for external drivers without trusted
usage. The Docker worker retains daemon authority on the trusted local host.
Next canonical task: NV-06 independent validation with positive, negative and
control fixtures linked to immutable evidence.

## 2026-09-23 — NV-05 fresh-session implementation handoff

**Outcome:** Replaced `tmp-implementationPlan.md` with a planning-only NV-05
handoff for declared foothold-scoped internal TCP access and a versioned
REST/console/MCP runtime capability manifest. NV-05 remains unchecked. The
completed NV-04 work, its live evidence, and the separate UI rebuild proposal
were committed locally as `f90d0e6`; nothing was pushed.

**Basis / files:** Read AGENTS, README, ROADMAP, TODO, relevant ADRs, the latest
journal entry and `.lab.yaml` in continuity order; inspected current provider,
binding, budget, gateway and console seams. Changed this journal and the handoff
only. No product code or verification gate changed or ran for this plan.

**Risks / next step:** The Docker foothold currently exposes `docker exec`,
not a proven SSH service. First implement and review ADR-0016 with a transport
spike that authenticates each stream and fixes its destination without widening
control-plane Docker access. Then build the durable lease, manifest and isolated
NV-05 live gate; update canonical status only after all required gates pass.

## 2026-09-23 — NV-04 durable budgets and stop controls complete

**Outcome:** Completed NV-04. The orchestrator now owns versioned action caps,
absolute deadlines, an atomic reservation ledger and sticky per-arena/system stop
gates. The account survives gateway reconnects and NV-02 replacement resets.
REST, attacker/operator MCP and the current Flask console use the same authority;
worker jobs and disposable helper starts recheck durable gates. Stop drains work,
reaper recovery settles interrupted PoC jobs, and final traces remain readable.
Unsupported token/cost hard caps refuse admission because current BYO-agent
drivers cannot supply trusted pre-execution usage bounds. ADR-0015 is accepted.

**Files:** Added migration `0007_add_budget_stop.py`, budget/stop models and
database operations, API and gateway routes/tools, worker/provider guards,
console controls, `docker-compose.nv04.yml`, `scripts/verify-nv04-live.py`,
tests and `docs/API.md`. Updated TODO, ROADMAP and README against passing gates.
The preexisting UI rebuild proposal and earlier journal entries remain intact.

**Verification:** Final `make release-check` on pinned Python 3.11.14 passed
Ruff 0.6.9, Bandit 1.9.4 (zero medium/high findings), 889 SQLite tests (two
PostgreSQL-only skips) and 891 PostgreSQL tests; each backend had six declared
integration deselections. Clean Alembic migration and API/console/MCP readiness
smoke passed. The PostgreSQL suite includes competing admission, setup-step and
stop/helper-start transactions. `make verify-nv04-live` passed with a 200/429
one-slot race, cross-process MCP budget persistence, queued-job refund,
running-job stop and cleanup, admission/stop race, killed-worker recovery,
HTTP/browser drain, system-stop restart persistence, deadline expiry and zero
final labeled resources. `make verify-nv02-live` and `make verify-nv03-live`
passed afterward. Saved evidence:
`docs/verification/nv04-live-2026-09-23.json`,
`docs/verification/nv02-regression-2026-09-23.json` and the refreshed
`docs/verification/nv03-live-2026-09-22.json` (`verified_at` is 2026-09-23).

**Risks / next step:** Current external-agent token/cost caps remain explicitly
unsupported until a driver exposes a trusted bound and usage feed. Synchronous
foothold/setup calls drain within their bounded timeout; stop does not preempt
an already running command. Docker-local is the live-verified provider. Next:
NV-05 scoped research access and runtime capability discovery.

## 2026-09-23 — NV-04 fresh-session implementation handoff

**Outcome:** Replaced the completed NV-03 `tmp-implementationPlan.md` handoff
with a concrete NV-04 plan for durable action/time budgets, explicit token/cost
accounting limits, per-arena/system stop, shared REST/MCP/console enforcement,
recovery and isolated live acceptance. NV-04 remains unchecked. The completed
NV-03 plan is preserved in commit `e778e30`; the separate UI rebuild proposal
is unchanged.

**Basis:** Read README, ROADMAP, TODO, relevant ADRs, latest journal and
`.lab.yaml`; inspected gateway process-local budgets, binding pause, setup
step accounting, NV-03 durable jobs, model usage seams, migrations, reaper and
release/live test entry points. No product code changed and no tests run for
this planning-only handoff.

**Risks / next step:** Direct REST and concurrent setup actions currently bypass
or race process-local/event-derived counters. External BYO agents lack trusted
pre-execution token/cost accounting. The next session starts with the proposed
ADR/charge matrix and PostgreSQL admission/stop races, then implements the
remaining plan and proves the live stop gate before closing NV-04.

## 2026-09-23 — Proposed full console rebuild plan

**Outcome:** Added `docs/UI_REBUILD_PLAN.md`, a proposed frontend remake with
researcher workflows, complete surface inventory, architecture and security
boundary, phased parity migration, cutover and acceptance gates. It proposes a
React/TypeScript frontend served through the existing Flask same-origin BFF.
This changes no product code or canonical NV status. A new ADR must explicitly
supersede ADR-0012's Flask/Jinja rendering choice before implementation.

**Basis:** Inspected the current WebUI routes, templates, JavaScript, CSS,
tests, ADR-0012, ROADMAP and TODO. Checked official React, Vite, React Router,
Playwright and W3C documentation for the proposed implementation and testing
approach. No usability study or runtime test was performed for this plan.

**Risks / next step:** The cost and visual direction remain provisional until a
route/action parity matrix, researcher walkthrough and two design concepts are
reviewed. Start with that phase-0 ticket; keep NV-04/NV-05 backend acceptance
separate and coordinate their new UI contracts.

## 2026-09-23 — NV-03 confined PoC execution complete

**Outcome:** Completed NV-03: durable confined Python jobs, REST/console/attacker
MCP, fixed-target Unix HTTP relay, browser proxy, worker-owned HTTP/browser
dispatch, encrypted source/results, admission slots, cancellation and recovery.
The selected-target PoC and all required live denial, interruption and cleanup
checks passed. The runner client is installed in the immutable trusted image.

**Closure failures found and fixed:** Docker archive APIs could not collect tmpfs
artifacts (use bounded trusted tar exec); proxy readiness was shorter than measured
startup; cancellation before helper creation lost its terminal state; teardown
raced in-flight helper creation; failed cleanup was not retried; expired queued
jobs retained slots; cancellation could race a claim; idempotency was not bound to
principal; the MCP verifier assumed structured rather than JSON text content.
Exit publication is now atomic and Docker exec exit status is polled after EOF.

**Files:** orchestrator models/migration/database/API/tasks/providers and trusted
runner/relay/proxy; helper_jobs.py; gateway tools; console routes/template/JS;
dedicated docker-compose.nv03.yml and live verifier; PoC/provider/gateway/migration
tests; ADR-0014 and API/operations/README guidance.

**Verification:** Final `make release-check` passed on pinned Python 3.11.14:
Ruff passed, Bandit found zero medium/high source findings, SQLite reported
879 passed/one PostgreSQL-only skip and PostgreSQL 880 passed, with six
integration deselections each. Clean migrations and API/UI/gateway smoke passed.
`make verify-nv02-live` passed after the lifecycle/worker changes.
Final rebuilt `make verify-nv03-live` passed on Docker server 29.7.2 and worker
Python 3.11.16. It exercised a useful selected-target PoC, transfer/artifacts,
positive controls for external and other-arena canaries, explicit direct-route
denials, relay rejection, browser redirects/subresources, resource pressure,
cancellation, console/MCP flows, killed-worker recovery without replay and reset
while a helper existed. Its final owned container/network/volume counts are all
zero. Sanitized IDs, image digests, outcomes and inventories are retained in
`docs/verification/nv03-live-2026-09-22.json`.

**Risks / next step:** Docker containers share the host kernel, so this remains
a Docker-local research boundary, not VM-grade hostile multi-tenancy. Raw TCP/UDP,
runtime package installs, durable aggregate budgets/system stop and general
foothold access remain unsupported or planned. Implement NV-04 next.

## 2026-09-22 — Astra review and NV-03 handoff for Sol

**Outcome:** Reviewed committed NV-01/02 status and replaced the completed NV-02
handoff with the NV-03 confined-PoC plan for Sol: durable worker-owned jobs,
target-scoped relay enforcement, bounded IO, cancellation/recovery, shared
authorization, REST/MCP/console workflow and isolated live acceptance.
NV-03 remains unchecked; no product feature is implemented by this plan.

**Files:** tmp-implementationPlan.md and this journal. The prior handoff remains
in commit 349e804. Local .lab.yaml still marks NV-02 open; canonical TODO and the
committed acceptance artifact take precedence over that stale local note.

**Verification:** Inspected delivery docs, relevant ADRs, recorded acceptance,
helper network/provider code, API/binding/gateway seams and verification entry
points. Documentation checked with git diff --check. No tests/live gates rerun;
prior passing counts remain historical evidence.

**Risks / next step:** Arena-segment attachment does not prove selected-target-only
policy, especially for arbitrary sockets/browser subrequests. Sol must implement
and prove containment, interruption cleanup and usable console/MCP behavior before
closing NV-03. Implementation and accepted ADRs remain unchanged.

## 2026-09-21 — Complete NV-02 target lifecycle and reset reproducibility

**Outcome:** NV-02 is complete. Deploy creation now persists an encrypted immutable
lifecycle recipe separately from observed runtime state, including requested versus
effective provider, compiled scenario, pinned inputs, runtime configuration, seed and
bounded readiness policy. Build reproducibility, reset eligibility and observed
equivalence are reported independently; manual setup, mutable images/builds and legacy
records remain honestly unsupported or unverified. Public projections omit environment
values, commands, seed values, readiness truth and private authorization notes.

Reset is an operator-only durable replacement operation: one atomic in-flight claim and
idempotency key produce one stable replacement UUID, destroy the source without rewriting
its record, deploy the saved recipe, compare observed baseline digests and retain links in
both audit trails. Requested and effective providers are stored separately. Duplicate
Celery delivery, lost enqueue, stale running operations and worker restart are reconciled;
expired authorization boundaries are rechecked before destructive work, and bindings or
setup consent are not copied. The console exposes lifecycle classification, observations,
operation state and replacement links with its existing CSRF boundary.

Docker-local readiness is arena-bound and bounded. Lifecycle tasks have soft/hard time
limits and SDK timeouts. Cleanup now collects removal errors, treats already-absent
resources idempotently, discovers anonymous volumes from owned mounts, avoids forcing
shared images, verifies the final inventory and retains `error_destroying` as a reaper-
retryable obligation. ADR-0013 records the replacement-reset decision.

**Files:** lifecycle manifest/service, API/tasks/provider/persistence/model and Alembic
changes under `cyber-range/services/scenario-orchestrator/`; console route/template;
`cyber-range/fixtures/nv02-reset/`; `docker-compose.nv02.yml`;
`scripts/verify-nv02-live.py`; focused API/lifecycle/migration/reaper/provider tests;
ADR-0013; operations/status docs; and
`docs/verification/nv02-live-2026-09-21.json`.

**Verification:** Final `make release-check` passed in the pinned Python 3.11.14
environment. Ruff passed; Bandit reported zero medium/high findings; SQLite reported
863 passed, one PostgreSQL-only concurrency test skipped and six integration tests
deselected; PostgreSQL reported 864 passed and six integration tests deselected. Clean
migrations and API/UI/MCP readiness smoke passed. The PostgreSQL run exercised two real
competing reset transactions and admitted one winner.

`make verify-nv02-live` passed on Docker client/server 29.7.2, API 1.55, Linux amd64.
It deployed the content-addressed synthetic fixture, mutated and recorded it, initiated
the first reset through the CSRF-protected console and the second through the API, retained
the HTTP transaction and finding after teardown, reset twice across three UUIDs with the
same observed baseline digest, verified no inherited bindings, killed the dedicated
worker during another deployment, withheld it during a queued teardown, reconciled both
records to `destroyed`, and found zero labelled containers, networks, volumes or images
across all five arenas. Two earlier attempts found and fixed local-image-ID validation and
an already-removed-network teardown race; only the final passing result is acceptance.

**Unresolved risks / next step:** Exact reset remains intentionally limited to immutable
Docker-local inputs with declared readiness; manual setup, mutable/network builds and
other providers do not claim equivalence. The next canonical item is NV-03 confined PoC
execution. It must reuse these ownership, timeout, cleanup and scope boundaries rather
than expanding participant access to the Docker control plane.

## 2026-09-21 — Astra planning handoff for Sol: NV-02

**Outcome:** Added a concrete implementation handoff for the next Sol run, scoped
to NV-02 target lifecycle/reset acceptance. The plan preserves canonical delivery
order and specifies immutable recipes versus observed state, replacement arenas
with retained evidence, durable idempotent reset operations, bounded readiness,
verified cleanup and restart/concurrency recovery. The user's explicit choice of
Sol for implementation supersedes the older Claude Code delegation instruction
for this task. No runtime feature or NV checklist item is completed by this plan.

**Files:** `tmp-implementationPlan.md` and this journal.

**Verification:** Read the delivery docs and relevant provider, persistence, build,
research-session and console ADRs; inspected manifest/preflight, API creation,
worker/reaper, Docker deploy/destroy, database/state and verification seams.
Documentation whitespace checked with `git diff --check`. No application tests,
live arenas, migrations or release gate were run for this documentation-only change.

**Unresolved risks / next step:** NV-02 remains open. Existing reset metadata is a
declaration rather than observed equivalence; provider cleanup can report success
after volume/image removal errors. Sol should implement the handoff and prove the
isolated live lifecycle path plus the supported release gate before marking NV-02
complete. NV-03 follows; NV-06 implementation still depends on the P0 runtime.

## 2026-09-16 — Complete NV-01 reproducible release/test environment

**Outcome:** NV-01 is complete. Added one documented clean-checkout command,
`make release-check`, which builds a dedicated Python 3.11.14 verifier from an
exact dependency lock, runs the source quality/security and SQLite gates, performs
clean Alembic plus API/console/MCP-gateway readiness smokes, and repeats the suite
against a disposable PostgreSQL service. The wrapper removes stale verifier state
before and after each run. CI now uses the same pinned interpreter, lock and Make
targets. Host `make check` refuses unsupported Python instead of silently using the
local 3.14 environment.

The gate consistently excludes local `.venv` and nested `venv` trees from Docker,
Ruff and Bandit, and excludes local `.env` files from the clean build context. This
fixed the review's Bandit defect and two broader variants discovered during the
first clean run. Docker/OpenTofu tests remain explicit integration work rather than
being silently counted as hermetic coverage.

**Files:** `.python-version`, `requirements-lock.txt`, `Dockerfile.verify`,
`docker-compose.verify.yml`, `scripts/release-smoke.py`, `scripts/verify-release`,
`Makefile`, `.dockerignore`, `ruff.toml`, `.github/workflows/ci.yml`,
`CONTRIBUTING.md`, `docs/OPERATIONS.md`, `README.md`, `ROADMAP.md`, `TODO.md`, and
this journal.

**Verification:** `make release-check` passed end to end on Python 3.11.14 with
Ruff 0.6.9 clean and Bandit 1.9.4 reporting zero medium/high findings. SQLite:
852 passed, 6 deselected. PostgreSQL 16.15: 852 passed, 6 deselected. The six
deselections are five tests requiring a live Docker daemon and one requiring
OpenTofu. The clean Alembic migration created the expected schema; unauthenticated
API `/health`, console `/login` with CSRF, and attacker MCP tool registration all
passed readiness smoke. `git diff --check` is part of the final handoff check.

**Unresolved risks / next step:** This gate deliberately does not mount the host
Docker socket and did not execute OpenTofu, so it makes no live arena lifecycle
claim. NV-02 is next: record target build/runtime/reset manifests and prove repeated
Docker-local deploy/reset, interrupted cleanup, and post-teardown evidence retention.

## 2026-09-07 — Reorganize research and agent-evaluation delivery

**Outcome:** Operator-requested documentation update only. Added NV-01–15 with dependencies
and acceptance criteria. P0 establishes a reproducible release/reset path, confined execution,
durable budgets/stop and scoped access. P1 strengthens independent validation and introduces
durable experiments, a small challenge library, Bughunt usefulness proof and record recovery.
P2 expands version/fix replay, fuzzing, binary/local VM and research/disclosure work only for
selected target needs. Discovery and evaluation remain first-class objectives; no platform
was archived and no new runtime/integration feature is claimed as implemented.

Reconciled stale guidance: dynamic Docker topologies, stance-scoped MCP and R1 HTTP
capture/replay are implemented. R1's old task slices remain a design/acceptance reference.
Cloud provider parity remains deferred. Existing ADRs are unchanged; this is delivery
sequencing and acceptance refinement, not a replacement for their technical boundaries.

**Files:** TODO.md (new), ROADMAP.md, README.md, AGENTS.md, docs/JOURNAL.md (new), and the
local Git-ignored .lab.yaml milestone summary. No code, infrastructure or operator data changed.

**Verification:** `git diff --check` passed. Python documentation checks found 15 unique open
NV task IDs and valid local checklist links (this journal completes the final link). Local
.lab.yaml parsed successfully. Dependencies/mapping retain R2/R3, D1–D4, E1–E5 and proof work;
implemented foundations are separate. No application tests were rerun for documentation edits.

**Review baseline, not a new full gate:** earlier today Ruff passed; source-only Bandit
(excluding .venv and nested venv) had zero medium/high findings; 121 focused tests passed.
The full Python 3.14 suite stalled in Starlette TestClient and was interrupted. Standard
make check scans an unintended nested venv. The cached Python 3.11 image lacks full test
dependencies. No main Compose stack was running, and no live arena or PostgreSQL suite was
verified. The August 18 result of 808 passes/six skips remains historical.

**Risks / next step:** NV-01 must restore the supported Python 3.11 full gate and correct
Bandit's exclusion before a professional-readiness claim. Then NV-02 proves target lifecycle
and reset; NV-09's one local agent workflow supplies evidence for continued investment.
Bughunt integration is planned, uses synthetic credentials and does not expose hidden truth
or operator-only evaluation exports to the participant.
