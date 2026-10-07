# Royal Command console default cutover — 2026-10-07

**Decision:** the operator manually reviewed Releases G–H on the live dev stack and
approved them ("Overall approved"). `/console` became the default UI.

## Switch

- `WEBUI_DEFAULT_CONSOLE` defaults to `true` (`cyber-range/webui/app.py`,
  `docker-compose.yml`). `/` and the post-login landing page redirect to `/console`.
- `WEBUI_DEFAULT_CONSOLE=false` restores the legacy home at `/`.
- `/?legacy=1` reaches the legacy home while the console is the default (console
  footer link). All legacy routes stay mounted in both settings.

## Fallback drill (dev stack, `docker-compose.dev.yml` bind-mount verified)

| Setting | `/` | `/?legacy=1` | `/console` |
|---|---|---|---|
| `false` | 200 legacy home | 200 | 200 |
| unset (default `true`) | 302 → `/console` | 200 | 200 |

The first drill attempt was invalid: recreating the WebUI without the dev override
served the Sep 29 image. It was repeated after the mount was restored (see
`docs/JOURNAL.md`).

## Evidence

- `tests/test_webui.py`: the default-switch test (including the `/?legacy=1` escape)
  and a fresh-interpreter test that the unset default is the console.
- Browser checks: `scripts/ui-release-{b,c,d,e,f,g,h}-check.cjs`,
  `scripts/ui-release-g-stepper-check.cjs`, `scripts/ui-assistant-rail-smoke.cjs`.
- Final post-cutover and review-fix `make release-check`: Ruff and Bandit clean;
  980 SQLite tests (4 skipped, 6 deselected); 984 PostgreSQL tests (6 deselected);
  migration/API/UI/gateway readiness smoke passed. See
  [focused merge review](ui-merge-review-2026-10-07.md).

## Not covered (UI-R1 stays open)

- Setup command output, the custom topology builder and non-Docker-local launches
  still use legacy pages.
- Forwards, archive removal and destroy-from-list were exercised with mocked service
  calls only.
- No formal accessibility review has been recorded beyond keyboard focus,
  reduced-motion and the skip link.
