# Acceptance stacks

Isolated, disposable Compose projects used by the live acceptance gates
(`make verify-nvXX-live`, `scripts/verify-*-live.py`, `scripts/ui-r1-*-check.cjs`).
Each file pins its own project name, loopback-only ports and throwaway
PostgreSQL/Redis, so a gate never touches a running main stack.

They are not needed to run Nidavellir. For that use the root files:

    docker-compose.yml          base stack
    docker-compose.dev.yml      development override (mock mode, live reload)
    docker-compose.prod.yml     production override
    docker-compose.verify.yml   release-check harness (make release-check)

## Invocation

Paths inside these files are relative to the repository root, so always pass
`--project-directory .` from the root:

    docker compose --project-directory . -f compose/acceptance/nv06.yml config
    docker compose -p nidavellir-nv14 --project-directory . \
      -f compose/acceptance/nv06.yml -f compose/acceptance/nv14.yml up -d

| File      | Gate                                   | Layers on       |
|-----------|----------------------------------------|-----------------|
| nv02.yml  | deploy / reset / interruption          | —               |
| nv03.yml  | confined PoC execution                 | —               |
| nv04.yml  | durable budgets / stop                 | —               |
| nv05.yml  | scoped research access                 | —               |
| nv06.yml  | independent validation; base of others | —               |
| nv07.yml  | paired evaluations                     | nv06            |
| nv10.yml  | encrypted record recovery              | nv06 + nv07     |
| nv14.yml  | NV-14 acceptance                       | nv06            |
| ui-r1.yml | operator console (needs --env-file)    | —               |
| ui-r4.yml | research checkout mount                | nv06            |

Records of past runs (kept locally, not published) cite the
historical root file names (`docker-compose.nvXX.yml`), which moved here
unchanged.
