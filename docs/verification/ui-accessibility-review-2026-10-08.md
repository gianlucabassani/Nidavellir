# Operator console accessibility review — 2026-10-08

Scope: the default React operator console, sign-in page, registered and custom
launch forms, shared routes, and the Overview, Setup, Forwards, Score, Findings,
Trace and Access arena tabs. Both light and dark themes were reviewed.

Automated scan: axe-core WCAG 2.0/2.1/2.2 Level A and AA rules across 41
page/theme combinations. Result: zero violations after fixes for station names,
tool links, profile avatar contrast and warning-status contrast.

Manual browser checks:

- Keyboard opened the Destroy confirmation, kept tab focus within the dialog,
  closed it with Escape, and returned focus to the triggering button.
- The custom topology station controls expose selection state and support
  keyboard activation in the console implementation.
- Launch forms and arena tabs reflowed at 320, 390, 1024 and 1440 CSS pixels
  without document-level horizontal overflow.
- The browser ran with `prefers-reduced-motion: reduce` enabled.

This review records the product team's implementation checks. It does not claim
third-party certification, screen-reader testing, or conformance beyond the
listed pages and checks. See `scripts/ui-r1-accessibility-check.cjs` and
`scripts/ui-r1-keyboard-check.cjs` for repeatable browser checks.
