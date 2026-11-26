# ADR-0019: Forge design system and console shell

- **Status:** Accepted
- **Date:** 2026-11-26
- **Deciders:** Nidavellir operator
- **Supersedes:** ADR-0017's visual-system paragraph ("Royal Command ... centered angular top navigation") only

## Context

An audit of the React console found it inconsistent. Across pages it used 25 font
sizes, 37 different gaps, 117 paddings and 171 hard-coded colours. Each page used
8–13 sizes, and 30–85% of its text was under 12 px.

Navigation was split three ways:
- a centred workspace switch;
- a Library dropdown holding seven unrelated pages;
- inside an arena, a second in-page tool menu.

Unfinished features looked the same as working ones. Operators asked for three things:
- to set up a target easily;
- to see which tools an arena offers and where to find each one;
- to always see which agents are connected and what they are doing.

They also asked that the public console look finished, and that anything not yet
implemented be disabled or marked.

The operator reviewed and approved a clickable prototype of the redesign.

## Decision

We adopt the **Forge** design system and a new console shell. The rules are
binding for new and ported views.

**Tokens** (`frontend/src/design/tokens.css`):
- **Surfaces** (page, surface, inset, raised) step by lightness and are separated
  by hairline borders. There are no shadows, except for pop-overs.
- **Gold** marks the brand, the primary action and "live". It is never a status.
- **Status colours** (ok, warn, bad, info, idle) mean status only, and always
  appear with an icon or dot and a text label.
- **Text colours** meet WCAG AA (4.5:1) on page, surface and inset, in both themes.
- **Text sizes** are named by job: micro 11, meta 12, ui 13, body 14, title 15,
  head 20 and display 28. Spacing uses a 4 px scale.
- **Legacy token names** stay as aliases until every page is ported.

**Type:**
- Geist Sans for words, Geist Mono for identifiers, numbers and times.
- Both are vendored as variable woff2 (geist 1.9.2) under the SIL Open Font
  License 1.1, with the licence next to the files.
- No font CDN and no new npm dependency.

**Identity kept, reduced:**
- the anvil emblem and the three workspace runes;
- a Nordic braid band under the top bar;
- cards with a gold tick and a cut top-right corner;
- a navy "fade" with a faint woven texture, used only on the top bar and hero cards.

The numbered "01 / …" panel captions are retired as pages are ported.

**Shell:**
- **Top bar:** the logo (a link home), the three workspaces (Research, Benchmark,
  Cyber Range), search (Ctrl/⌘-K), a connected-agents indicator, the Copilot
  launcher and the attention bell.
- **Agents indicator and bell:** both open drawers fed by the live agents board.
  The board is one shared push stream per tab.
- **Left sidebar:** the only menu, one per workspace. The former Library pages
  move into it:
  - Research: Arenas, Agents board, Findings, Evidence, Campaigns, Source review.
  - Benchmark: Evaluations, the Registry, Agents.
  - Cyber Range: New arena, Targets, Scenarios.
  - Profile, Platform settings, the Activity log and the legacy console move to
    the account menu.
- **Inside an arena:** the sidebar becomes the arena's menu:
  - the arena's name, state and gate;
  - Overview and Live;
  - Tools, each with a ready dot from the provider's capability report;
  - Record;
  - Configure.
- **Sidebar foot:** account and theme are pinned there. Only the menu above
  them scrolls.
- **Scrolling:** the window stays the scroller, so the router's scroll
  restoration keeps working. Below 860 px the sidebar is an overlay opened from
  the top bar.

**Feature states:**
- Every visible feature is *ready*, *Preview* (works with stated limits) or
  *Planned* (visible, not interactive, with its reason).
- A disabled control always says why. Nothing that is not implemented may look
  usable.

## Alternatives considered

- **Restyle page by page without a shell change:** this leaves the Library
  dropdown and the double arena menu in place, which were the main sources of
  confusion.
- **Adopt a component or CSS framework:** it would add dependencies and a second
  styling vocabulary to a codebase that already has one. Plain CSS with tokens is
  enough.
- **Load fonts from a CDN:** this adds a third-party request to an operator
  console that should work offline and leak nothing.

## Consequences

- Pages not yet ported take the new palette, type and primitives (card, button,
  badge, label, fields) through the classes they already use. Their layouts are
  ported in follow-up items:
  - UX-17: Research overview and arena dashboard;
  - UX-18: findings;
  - UX-19: live timeline;
  - UX-20: Copilot panel;
  - then UX-14 and UX-15.
- Each port removes the page's hard-coded colours and sizes. The legacy aliases
  go away once no stylesheet uses them.
- `scripts/ux16-browser-check.cjs` checks every sidebar destination in both
  themes, the pinned sidebar foot, the home link, the drawers and phone width.
  UX-15 runs these checks in CI.
