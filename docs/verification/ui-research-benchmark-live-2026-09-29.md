# Royal Command Research and Benchmark live browser evidence

**Date:** 2026-09-29  **Provider:** Docker-local  **Browser:** Chromium

## Research

An isolated PostgreSQL/Redis/worker/WebUI stack at `docker-compose.nv02.yml`
served the packaged React console. Chromium uploaded a local tar source bundle,
reviewed its SHA-256 identity, launched arena
`e9a19813-29ce-438c-92c9-6148e9938aec`, ran `/bin/sh /opt/sut/check.sh`
in the setup workbench, and finished setup. The saved prearm values shown by
the browser were 1800 seconds, 12 commands and setup egress enabled. A
networkless Python PoC reached `succeeded` as job
`f248cc24-404e-4f2b-86a9-ad87828a5f74`. The browser recorded the
operational observation “Research bundle observation”, destroyed the arena,
and reopened the finding on the retained record. This observation makes no
vulnerability claim.

The first attempt exposed a zero-minute stuck-arena reaper in the disposable
Compose configuration; it was changed to five minutes. The second attempt
exposed an arena audit endpoint that ignored its `type` query, causing the
setup projection to show an incorrect finished state and omit planned time.
The endpoint now filters the events before applying its limit. An intermediate
attempt submitted a PoC but destroyed the arena before the job finished;
the final run waited for its terminal `succeeded` state.

## Benchmark

The isolated NV-06/NV-07 stack hosted a reproducible authorization fixture.
Two pinned scripted MCP builds and a calibration challenge were prepared with
the existing NV-07 fixture. Chromium registered a three-seed suite, launched
evaluation `12992c52-b700-4cbb-ba02-1fbf37b1e9ff`, and viewed the
completed comparison. All six trials completed; three starting-state pairs
matched; infrastructure failures were zero; the candidate minus baseline
verified difference was +1. The constant difference has a **degenerate**
interval, and the UI explicitly limits the conclusion to calibration. The
result view now formats numeric values and interval labels for operators and
uses stacked metric cards on phones.

## Browser and cleanup checks

The live Research archive and Benchmark result had no page-level horizontal
overflow or JavaScript exceptions at 1440, 1024, 390 and 320 px. This is a
reflow check, not a WCAG audit. Screenshots:

- [Research retained record](../assets/ui-concepts/renders/royal-command-research-archive-live.png)
- [Benchmark result, desktop](../assets/ui-concepts/renders/royal-command-benchmark-live.png)
- [Benchmark result, phone](../assets/ui-concepts/renders/royal-command-benchmark-live-mobile.png)

The Research arenas from the exploratory and final runs, the Benchmark source
arena and all six trial arenas each had zero labeled containers and networks
after teardown. Both disposable Compose stacks and their volumes were removed.
The main mock development stack was not changed.

The final pinned `make release-check` passed Ruff, source-only Bandit, 963
SQLite tests (4 skipped, 6 deselected), 967 PostgreSQL tests (6 deselected),
and migration/API/UI/gateway smoke. TypeScript, Prettier, Vite build and
`git diff --check` passed.

## Remaining gate

This evidence does not establish full legacy route/action parity, manual
keyboard/screen-reader/WCAG review, three-researcher task observation,
session-expiry/role-denial browser coverage, a fallback drill or the default
route cutover. UI-R1 therefore remains open; `/console` stays opt-in.
