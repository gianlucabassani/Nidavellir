# Royal Command merge review — 2026-10-07

Scope: `main` (`2f3b2a09444623d53d4db165d87061aab3597ffc`) to
`ui/royal-command`, with focused independent Standards and Spec reviews of
Flask BFF score, trace, service forwards and archive delete/clear endpoints.
The initial review pinned `95b03f4`; corrections were independently re-reviewed.
This is a focused backend review, not an exhaustive review of every file in the
console branch. Specs: ADR-0017, UI_REBUILD_PLAN, UI_ROUTE_ACTION_MATRIX and UI-R1.
The repository has no `docs/agents/issue-tracker.md`; local specs supplied the
review context.

## Standards

Two P2 findings, both resolved:

- Forward reads discarded service success flags and returned a successful empty
  lease list on failure. Both authoritative reads must now succeed; otherwise
  the BFF returns a retryable 503 and the browser shows its error state.
- Each forward retry generated another action key, risking duplicate leases and
  budget charges after an uncertain response. The browser now retains a key for
  the same selected destination until success; the BFF validates and forwards it.
  The service checks principal, request digest and binding generation, and
  returns an existing matching lease before reserving another budget action.

Global Flask login and CSRF protection cover these routes. Archive deletion
remains delegated to operator-only service endpoints with terminal-state checks
and service-owned audit. Scoring remains service-owned. No additional blocking
standard or heuristic finding remained in the focused correction review.

## Spec

Three P2 findings, all resolved (the failed forward-read finding overlaps Standards):

- Trace read `scaffold`/`stance` instead of the export's `nv.harness`/`nv.stance`.
  The projection now follows the actual export schema.
- A 200-event unfiltered presence check hid older agent activity. Presence queries
  now filter by agent event type before limiting. The regression builds an actual
  eval export from an agent session followed by 200 unrelated events.
- Failed forward reads appeared as “No leases”; the 503/error state resolves it.

No remaining blocker was found in the focused correction review.

## Verification

- Regression tests failed on the original behavior before fixes; the full WebUI
  test file passed after fixes in the pinned Python 3.11 container.
- `scripts/ui-forward-retry-check.cjs` failed before the browser fix, then passed:
  stable key across an uncertain response, a new key after success, a new key for
  a changed destination, and no page errors. Every API request was intercepted.
- Release H browser smoke: 25/25, with mutations intercepted; no service mutation.
- TypeScript, Prettier and Vite production build passed. Separately staged
  Release G and Release H frontend snapshots also built successfully.
- Final corrected `make release-check`: Python 3.11.14; Ruff clean; Bandit zero
  medium/high findings; SQLite 980 passed, 4 skipped, 6 deselected; PostgreSQL
  984 passed, 6 deselected; migration/API/UI/gateway readiness smoke passed.
  The four SQLite skips require PostgreSQL transaction/race semantics. Six
  integration deselections require live Docker or OpenTofu.
- `git diff --check` passed.

## Reconciliation with current main

PR #2 initially conflicted because the UI and research branches had diverged.
Merging `main` (`2f3b2a0`) required resolution only in ISSUES and JOURNAL. All
entries from both branches were retained. The reviewed BFF, browser component
and WebUI tests are unchanged. The combined-tree pinned release gate passed:
SQLite **1094 passed, 4 skipped, 6 deselected**; PostgreSQL **1098 passed,
6 deselected**; clean Ruff/Bandit and migration/API/UI/gateway smoke. TypeScript,
Prettier and Vite passed. The UI diff against main passes whitespace checks;
existing main evidence logs were retained verbatim.

## Remaining boundary

UI-R1 stays open: setup command output, custom topology authoring and non-Docker
launches still use legacy; forwards, archive removal and destroy-from-list need
real-service browser verification; session-expiry, CSRF-denial and reconnect
journeys and a formal accessibility review still need recorded evidence.
Retry keys persist only while the workspace remains mounted with the same
selected destination; reloading or navigating away starts another action.
Legacy fallback remains available. The `forge-review` mock arena and rejected
reference artifacts were left untouched.
