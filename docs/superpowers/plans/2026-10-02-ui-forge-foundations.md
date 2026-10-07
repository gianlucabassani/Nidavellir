# Forge console foundations (checkpoint C1) Implementation Plan

> **Status 2026-10-02: executed, rejected by the operator, reverted.** Only the Library dropdown was kept. Do not re-execute this plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Operator rule for this project:** implementation is done directly by the coding agent in-session (no delegation to other coding services). Do not commit unless the operator asks; `cyber-range/webui/frontend/` is currently untracked, so a baseline tarball was taken before editing.

**Goal:** Give the opt-in `/console` one coherent Nidavellir visual system (royal-navy Day/Night tokens, self-hosted Geist + runic marks, one shape/motion rule, a refitted floating nav and theme-locked Forge surfaces) without changing routes, services, or behaviour.

**Architecture:** A new `src/theme/` layer owns tokens, fonts and base rules. Legacy variable names used by `styles.css` are kept as aliases of the new tokens so ~400 existing usages adopt the new palette without a rewrite; hard-coded colours in the shell, Forge, rail, assistant and topology are replaced by tokens. Shared components (`PageHead`, `Panel`, `Rune`) lose decorative eyebrows/overlines. A Playwright foundation smoke script encodes the acceptance checks and is written first.

**Tech Stack:** React 19, TypeScript 5.9, Vite 7, plain CSS; `@fontsource-variable/geist`, `@fontsource-variable/geist-mono`, `@fontsource/noto-sans-runic` (pinned exact); Playwright (existing local install) for browser checks.

**Spec:** the approved proposal in the 2026-10-02 session ("Design system", "Application shell", "Implementation order" sections), summarised under Global Constraints. Background: `docs/UI_REBUILD_PLAN.md`, ADR-0012, ADR-0017, `docs/verification/ui-assistant-navigation-2026-10-01.md`.

## Global Constraints

- All visible copy in English, sentence case; no section-number labels on non-sequences; no `—` as an empty value (use words such as "Not set").
- Tokens (Night / Day): ground `#0B1222`/`#E8EBF0`; surface `#111B2E`/`#F6F7F9`; raised `#172440`/`#FFFFFF`; line `#24324D`/`#CBD2DD`; text `#E6EAF2`/`#142036`; muted `#93A0B8`/`#55617A`; brass `#D4A548`/`#8A6618`; nav bar `#0E1830` in both themes.
- Semantic: ok `#2F9E77`/`#6FD3AE`, warn `#B7791F`/`#F0B357`, danger `#B4434F`/`#FF7A86` (day/night). Stances: attacker `#D9536A`, MITM `#8E6CD8`, defender `#3D8BD9`.
- Type: Geist Sans UI, Geist Mono for digests/IDs/code/logs; sizes 12/13/14/16/20/24; weights 400/500/600; tabular numerals for counts, budgets, times; page title 20px.
- Runes only for Research ᚲ, Benchmark ᛏ, Cyber Range ᚱ (C1); Stop ᛁ and Verify ᛊ arrive with their controls later. Always beside a text label, `aria-hidden`.
- Shape: containers one 8px cut corner (top-right); controls/chips radius 2px; no pills; shadows only on overlays, navy-tinted.
- Motion: 120/180/240ms, `cubic-bezier(.2,0,0,1)`; no page-load animation; reduced motion → none.
- Nav: centered, max-width 1120px, height 56px, top offset 12px, single line ≥1024px; <760px workspaces move to a labelled bottom tab bar.
- Day is the default theme (ADR-0017); theme preference may use localStorage; nothing else new is stored.
- One theme per page: no navy block inside a Day page except the nav bar chrome.
- Service authority unchanged: no BFF, auth, budget, lifecycle or validation change in C1.
- Fonts self-hosted through the Vite bundle; no external font/CDN requests.
- Legacy aesthetic backup `docs/assets/legacy-console-reference/2026-09-28/` is not modified.

## Review Focus

1. Theme switch at runtime: switching Day↔Night must restyle Forge canvas, rail flyouts, assistant and topology without reload (no hard-coded colours left there).
2. Narrow widths 320/390: bottom tab bar must not cover the assistant launcher or page content (body gets bottom padding); no horizontal document overflow.
3. Runic glyph fallback: if the runic font fails to load, the label text still identifies the workspace (glyph is decorative only).
4. Contrast: brass text on Day surface and muted text on both surfaces meet WCAG AA 4.5:1.
5. Keyboard: focus ring visible on nav, tab bar, theme toggle and account menu in both themes.

Each is asserted in `scripts/ui-foundation-smoke.cjs` (Task 1) and must pass by Task 6.

---

## File structure

- Create `cyber-range/webui/frontend/src/theme/tokens.css` — new tokens (Day/Night), legacy aliases, semantic and stance colours, motion and shape tokens.
- Create `cyber-range/webui/frontend/src/theme/base.css` — font faces import, base typography, focus, press feedback, reduced-motion rule, `.nv-cut`, `.mono`, tabular numerals.
- Create `cyber-range/webui/frontend/src/theme/shell.css` — floating nav, status ribbon, bottom tab bar, account menu.
- Modify `cyber-range/webui/frontend/src/main.tsx` — import order, nav markup (emblem, Library menu, theme toggle icon, bottom tab bar), status ribbon.
- Modify `cyber-range/webui/frontend/src/ui.tsx` — `Rune` uses runic glyphs; `PageHead` without overline, optional subtitle; `Panel` eyebrow optional and not rendered.
- Modify `cyber-range/webui/frontend/src/styles.css` — remove old token blocks and old shell rules; rename `--purple*` to `--accent-ink*`.
- Modify `cyber-range/webui/frontend/src/arena/forge.css`, `arena/navigation.css`, `shared/assistant.css`, `topology/SegmentMap.tsx` — tokens only.
- Modify the 16 `PageHead` callers — drop `overline`; workspace homes drop marketing subtitles; arena/evaluation detail carry the short id in the subtitle.
- Modify 7 `—` empty-value sites.
- Create `scripts/ui-foundation-smoke.cjs` — acceptance checks + renders.
- Modify `cyber-range/webui/frontend/package.json`, `package-lock.json` — three pinned font packages.
- Create `docs/verification/ui-forge-foundations-2026-10-02.md`; append `docs/JOURNAL.md`.

### Task 1: Foundation acceptance script (fails first)

**Files:** Create `scripts/ui-foundation-smoke.cjs`

**Interfaces:** Produces renders in `$NV_RENDER_DIR` (default scratch dir) named `foundation-<page>-<theme>-<width>.png`.

- [ ] **Step 1: Write the script** asserting, for `/console?workspace=research|benchmark|range` and the archived arena `?tab=forge`, in Day and Night, at 1440/1024/390/320:
  - `getComputedStyle(document.body).fontFamily` starts with `"Geist`;
  - no document horizontal overflow;
  - nav (`.command-bar`) height ≤ 58px at ≥1024 and max-width ≤ 1120px;
  - at 390/320 `.workspace-tabbar` is visible with 3 links whose text is Research/Benchmark/Cyber Range;
  - in Day, `.forge-workbench` background luminance > 0.6 (theme lock); in Night < 0.1;
  - no visible text matching `/^\d{2} \/ /` inside `main`;
  - contrast(brass text on surface) ≥ 4.5 and contrast(muted on surface) ≥ 4.5 using computed token values;
  - with `reducedMotion: 'reduce'`, `.forge-workbench` `animationName` is `none`;
  - Tab from the skip link reaches a nav item whose `outlineStyle` is not `none`;
  - no page errors.
- [ ] **Step 2: Run it** — `NV_PLAYWRIGHT_MODULE=/home/prime/Projects/osint/web/node_modules/playwright NV_CHROMIUM_PATH=/home/prime/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome node scripts/ui-foundation-smoke.cjs`. Expected: FAIL on the font assertion (Inter).

### Task 2: Tokens, fonts and base rules

**Files:** Create `src/theme/tokens.css`, `src/theme/base.css`; modify `styles.css` (lines 1–50 token blocks and the `--forge-rule` block at ~3003), `main.tsx` imports, `package.json`/lock.

**Interfaces:** Produces tokens `--nv-ground --nv-surface --nv-raised --nv-line --nv-text --nv-muted --nv-brass --nv-brass-ink --nv-bar --nv-bar-line --nv-bar-text --nv-ok --nv-warn --nv-danger --nv-attacker --nv-mitm --nv-defender --nv-dur-1/2/3 --nv-ease --nv-radius --nv-cut --nv-shadow-overlay`, and legacy aliases `--page --surface --surface-soft --ink --muted --subtle --line --line-soft --accent --accent-ink --accent-soft --gold --gold-ink --bar --bar-edge --bar-ink --success(-soft) --danger(-soft) --warning(-soft) --shadow --display --forge-rule --forge-haze`.

- [ ] **Step 1:** `npm install --save-exact @fontsource-variable/geist@5.3.0 @fontsource-variable/geist-mono@5.3.0 @fontsource/noto-sans-runic@5.3.0` in `cyber-range/webui/frontend`.
- [ ] **Step 2:** Write `tokens.css` with the Global Constraints values; `:root` = Day, `:root[data-theme="night"]` = Night; alias block maps legacy names onto `--nv-*` (e.g. `--page: var(--nv-ground)`, `--surface-soft: var(--nv-raised)` in Night / a `color-mix` 4% navy step in Day, `--accent: var(--nv-brass)`, `--accent-ink: var(--nv-brass)`, `--gold: var(--nv-brass)`).
- [ ] **Step 3:** Write `base.css`: `@import` the three fontsource CSS entry points; `:root { font-family: "Geist Variable", system-ui, sans-serif; font-size: 14px; }`; `.mono, code, pre, kbd, samp { font-family: "Geist Mono Variable", ui-monospace, monospace; }`; `.rune-glyph { font-family: "Noto Sans Runic", serif; }`; `font-variant-numeric: tabular-nums` on `table, time, .status, .numeric`; focus ring `2px solid var(--nv-brass)` offset 2px; `button:active:not(:disabled), .button:active { transform: translateY(1px); }`; `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }`; `.nv-cut { clip-path: polygon(0 0, calc(100% - var(--nv-cut)) 0, 100% var(--nv-cut), 100% 100%, 0 100%); }`.
- [ ] **Step 4:** In `styles.css` delete the two `:root` token blocks at the top and the `--forge-rule/--forge-haze` blocks; `sed` rename `--purple-soft` → `--accent-soft`, `--purple` → `--accent-ink`; replace `font-family: Georgia, serif;` (brand mark) and bare `monospace` declarations with the mono token.
- [ ] **Step 5:** `main.tsx`: `import "./theme/tokens.css"; import "./theme/base.css";` before `./styles.css`.
- [ ] **Step 6:** `npm run build` passes; smoke font assertion passes.

### Task 3: Floating nav, status ribbon, phone tab bar

**Files:** Create `src/theme/shell.css`; modify `main.tsx` header block; remove superseded shell rules from `styles.css` (`.site-header` … `.profile-menu`, `.simulation-strip`, `.theme-toggle`, `.utility-nav`, `.tools-menu`, and their media queries).

**Interfaces:** Consumes Task 2 tokens. Produces classes `.site-header .command-bar .brand .workspace-nav .library-menu .theme-toggle .profile .status-ribbon .workspace-tabbar`.

- [ ] **Step 1:** Header markup: brand = `<img src="/static/anvil_logo.png" alt="">` + "Nidavellir"; workspace buttons (rune + label); a `<details className="library-menu">` "Library" with Targets/Agents/Evidence/Activity (inline links removed); theme toggle with inline SVG sun/moon, visible text "Day"/"Night" ≥1024px, `aria-label` kept; account menu (Profile, Platform settings, Log out) unchanged in behaviour.
- [ ] **Step 2:** Status ribbon: render `simulationMode` as `.status-ribbon` directly under the bar, same max-width, text "Mock mode: actions are simulated in this development stack."
- [ ] **Step 3:** Bottom tab bar `<nav className="workspace-tabbar" aria-label="Workspaces">` rendered always, visible only <760px via CSS; three `<a>` with rune + label, `aria-current`; body `padding-bottom: 64px` <760px; assistant launcher bottom offset raised above the bar <760px.
- [ ] **Step 4:** `shell.css`: bar `max-width:1120px; height:56px; margin:12px auto 0;` navy `var(--nv-bar)`, 1px `var(--nv-bar-line)`, `.nv-cut`, overlay shadow; workspace items 40px high, active = brass 2px underline + brass text; ≥760 <1024 hide wordmark text and theme label; <760 hide `.workspace-nav`.
- [ ] **Step 5:** Smoke nav/tab bar/overflow/focus assertions pass.

### Task 4: Theme-locked Forge, rail, assistant and topology

**Files:** Modify `arena/forge.css`, `arena/navigation.css`, `shared/assistant.css`, `topology/SegmentMap.tsx` (grid pattern stroke) and the topology/status rules in `styles.css`.

- [ ] **Step 1:** Replace every hex in `forge.css` with tokens: workbench bg `--nv-surface`, panels `--nv-raised`, lines `--nv-line`, text `--nv-text`/`--nv-muted`, accent `--nv-brass`; drop `--forge-*` local hexes; remove `forge-reveal` page-load animation.
- [ ] **Step 2:** Same for `navigation.css` and `assistant.css` (assistant panel `--nv-raised`, overlay shadow token).
- [ ] **Step 3:** Topology: station fill `--nv-raised`, stroke `--nv-line`, selected stroke `--nv-brass`; foothold station gets a 4px left stripe `--nv-attacker`; SVG grid pattern stroke `currentColor` at 0.05 opacity via CSS class.
- [ ] **Step 4:** Smoke theme-lock assertion passes in Day and Night; visually check day/night forge renders.

### Task 5: Shared components and copy

**Files:** Modify `ui.tsx`, 16 `PageHead` callers, 7 `—` sites, `range/new.tsx`/`research/new.tsx`/`benchmark/new.tsx` eyebrows only if not sequences (they are steps: keep, sentence case).

- [ ] **Step 1:** `Rune` renders `<span className="rune rune-glyph" aria-hidden="true">{ {research:"ᚲ",benchmark:"ᛏ",range:"ᚱ"}[kind] }</span>`.
- [ ] **Step 2:** `PageHead`: remove `overline`; `subtitle?: string` rendered only when given; h1 20px/600 via CSS.
- [ ] **Step 3:** `Panel`: `eyebrow?: string`, not rendered; callers keep compiling. Remove all 64 `eyebrow="NN / …"` props with a scripted edit so no dead props remain.
- [ ] **Step 4:** Research/Benchmark/Cyber Range homes: no subtitle. Arena: subtitle `${scenario} · ${provider label} · ${id.slice(0,8)}`. Evaluation detail: id in subtitle.
- [ ] **Step 5:** Replace `"—"` empty values with `"Not set"` (setup budget, preflight source) or `"None"` (counts).
- [ ] **Step 6:** `npm run check` and `npm run build` pass; smoke eyebrow assertion passes.

### Task 6: Verify, render, record

- [ ] **Step 1:** `npm run check && npm run build`; `git diff --check`.
- [ ] **Step 2:** Full smoke at 1440/1024/390/320, Day + Night; renders saved to `docs/assets/ui-concepts/renders/foundation-*-2026-10-02.png`; existing `scripts/ui-assistant-rail-smoke.cjs` still passes.
- [ ] **Step 3:** `make release-check` (pinned gate) from repo root; record counts.
- [ ] **Step 4:** Write `docs/verification/ui-forge-foundations-2026-10-02.md` (what changed, renders, checks, limits) and append the dated `docs/JOURNAL.md` entry. UI-R1 stays open.
- [ ] **Step 5:** Stop and show the operator the renders before C2.

## Later checkpoints (planned in detail only after C1 approval)

- **C2 Arena frame:** context bar, capability-driven tool registry (`/arenas/{id}/capabilities`), rail with hover intent + ⌘K, session-target handoff, tool template on HTTP; states gallery fixtures.
- **C3:** layered fixed-scale topology for N nodes, setup stepper → history, docked assistant with correct status.
- **C4:** tool template across remaining tools; workspace homes as queue + list layouts.
