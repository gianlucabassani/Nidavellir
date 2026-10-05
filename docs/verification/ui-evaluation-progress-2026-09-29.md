# Royal Command evaluation progress — 2026-09-29

**Scope:** the opt-in Benchmark evaluation detail view and its operator-only
same-origin projection. The local browser check used intercepted fixture
responses; it did not run a real agent suite.

## Result

- The projection now returns total, running and terminal trial counts, each
  trial's baseline/candidate side and challenge ID, and a bounded operational
  failure reason. It continues to exclude the run's build configuration,
  private challenge truth, worker claim and trial transcript.
- While the evaluation is queued or running, the React view refreshes every
  eight seconds when visible, refreshes on return to the tab, and stops polling
  when the state becomes terminal. The view distinguishes in-progress results
  from a completed evaluation with no matched pairs.
- Chromium saw a running evaluation transition to complete after two BFF reads,
  displayed an infrastructure failure reason, and found no document overflow
  at 1440, 390 or 320 px. Its desktop running and mobile failure renders were
  inspected. A separate control-name scan on 12 main console routes found no
  visible unnamed buttons, inputs, selects, textareas or links; that scan is
  narrower than the planned accessibility review.
- `npm run check` and `npm run build` passed. The pinned `make release-check`
  passed with Ruff and Bandit clean, SQLite 962 passed/four skipped/six
  deselected, PostgreSQL 966 passed/six deselected, and migration/API/UI/gateway
  smoke passed. The packaged WebUI Docker build passed.

## Still required

Run an actual Docker-local paired evaluation through the browser, including
interrupted/retried trials and retained evidence. Complete action/deep-link
parity and the keyboard, focus, screen-reader, zoom, usability and fallback
checks in the UI rebuild plan. UI-R1 remains open.
