# Forge foundations (checkpoint C1) — rejected

**Status:** Rejected by the operator on 2026-10-02 and reverted. Kept as a record of the direction not to take: it lost the navy-on-stone contrast and the original bar character. Only the Library dropdown was kept.

Plan: [docs/superpowers/plans/2026-10-02-ui-forge-foundations.md](../superpowers/plans/2026-10-02-ui-forge-foundations.md).
The opt-in `/console` now has one visual system. Routes, BFF contracts, authorization, budgets, lifecycle and credential handling are unchanged.

## What changed

- **Tokens:** `src/theme/tokens.css` defines Day (cool navy-tinted stone) and Night (royal navy) palettes, one brass accent, status and stance colours, shape and motion values. Legacy variable names are aliases so older rules adopt the palette.
- **Type:** Geist Sans, Geist Mono and a five-glyph runic face are bundled with the console (no external font requests). Page titles are 20 px; panel headings 16 px; tabular numerals for tables and times.
- **Shell:** a centered 1120 px, 56 px navy bar with the anvil emblem, workspace runes (Research ᚨ, Benchmark ᛏ, Cyber Range ᚱ) beside text labels, a Library menu for Targets, Agents, Evidence and Activity, an SVG theme toggle and the account menu. Mock mode is a status ribbon under the bar. Below 760 px the workspaces move to a labelled bottom tab bar. Menus close on outside click and Escape.
- **Theme lock:** the Forge canvas, rail, assistant, topology and legacy navy panels use tokens, so Day and Night restyle everything at runtime. Attacker stations carry the attacker stance colour.
- **Copy and decoration:** numbered section labels, page overlines, decorative grids, page-load animations, glows and ALL-CAPS labels are removed. Empty values use words ("Not reported", "Not set") instead of a dash. Topology counts pluralize.

## Evidence

- `scripts/ui-foundation-smoke.cjs`: 177 checks pass. It first failed 120 of 177 before the changes (font, nav size, tab bar, labels, contrast, theme lock). Covers 4 pages x Day/Night x 1440/1024/390/320 px, Geist font, no horizontal overflow, nav height and width, phone tab bar labels, no numbered labels, forge theme lock, brass and muted contrast at least 4.5:1, keyboard focus ring in the nav, reduced motion and no page errors.
- `scripts/ui-assistant-rail-smoke.cjs` (mocked model, no real provider) still passes.
- TypeScript, Prettier and the Vite build pass. The pinned `make release-check` passed: 964 SQLite tests (4 skipped, 6 deselected), 968 PostgreSQL tests (6 deselected) and the migration/API/UI/gateway smoke. The image build ran `npm ci` against the updated lockfile.
- Renders (Day and Night, 1440 and 390): [research](../assets/ui-concepts/renders/foundation-research-day-1440-2026-10-02.png), [benchmark](../assets/ui-concepts/renders/foundation-benchmark-night-1440-2026-10-02.png), [cyber range](../assets/ui-concepts/renders/foundation-range-day-1440-2026-10-02.png), [arena night](../assets/ui-concepts/renders/foundation-arena-night-1440-2026-10-02.png), [arena day](../assets/ui-concepts/renders/foundation-arena-day-1440-2026-10-02.png), [phone](../assets/ui-concepts/renders/foundation-research-night-390-2026-10-02.png). All 16 are in `docs/assets/ui-concepts/renders/`.

## Limits

The dev stack holds only archived two-node mock arenas, so active, failed, stopped and larger topologies were not visually reviewed; C2 adds a states gallery. Home-page card grids, the Arena frame, target handoff, topology layout, setup flow and assistant docking are unchanged by design. No real model provider or lifecycle action was exercised. UI-R1 remains open.
