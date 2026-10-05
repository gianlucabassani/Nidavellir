# Royal Command scenario authoring — 2026-09-29

**Scope:** opt-in React `/console/scenarios` and `/console/scenarios/import` in
the local development Compose stack with `MOCK_MODE=true`. Legacy routes
remain available. The [review renders](../assets/ui-concepts/README.md) show
the library and the reviewed import form at desktop and phone widths.

## Checks completed

- Chromium loaded the library from the running same-origin BFF and displayed
  six registered scenarios with selectable topology. The search/filter and
  selected scenario are URL-owned state.
- Chromium submitted a Nidavellir v3 YAML spec for preview, then imported a
  temporary pack, fetched its registered topology and deleted the pack. The
  preview/import/topology/delete requests returned HTTP 200. The temporary
  `ui-smoke-pack-20260929` registration was removed.
- Offline Vulhub Compose preview returned a valid review without fetching a
  repository or persisting a pack. Editing a reviewed spec disabled Import
  until it was validated again.
- The import view had no document overflow at 1440, 1024, 390 or 320 px;
  the library had none at 1024, 390 or 320 px. Desktop and 390 px renders were
  inspected.
- `make release-check` passed: Ruff and Bandit clean; SQLite 962 passed,
  four PostgreSQL-specific skips, six integration deselections; PostgreSQL
  966 passed, six integration deselections; migration/API/UI/gateway smoke
  passed.
- The packaged `docker compose build webui` completed with TypeScript and
  Vite production build in the pinned Node stage.

## Limits before default switch

The Compose browser checks used mock infrastructure. They did not launch a
Docker-local scenario, verify repository-backed Vulhub conversion, or exercise
model generation against a configured model. Exact legacy action and deep-link
parity, live Research/Benchmark/Cyber Range journeys, accessibility/usability
review and the fallback drill remain open under UI-R1. The default layout has
not switched.
