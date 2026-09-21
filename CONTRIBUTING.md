# Contributing to Nidavellir

Thanks for helping build Nidavellir. This guide gets you from clone to green tests.

## Development setup

```bash
# 1. Clone & enter
git clone https://github.com/gianlucabassani/Nidavellir.git
cd Nidavellir

# 2. Create a virtualenv with the supported interpreter (.python-version)
python3.11 -m venv .venv && source .venv/bin/activate

# 3. Install the verified runtime + dev dependency lock
make install-dev      # == pip install -r requirements-lock.txt

# 4. Run the clean release gate (recommended before claiming a task complete)
make release-check    # pinned Python 3.11, SQLite + PostgreSQL, smoke checks
```

You do **not** need OpenStack or Redis to develop or run the test suite — the
tests run in `MOCK_MODE=true` and stub the task queue. `make check` is the faster
host loop and intentionally refuses non-3.11 Python. The release gate needs Docker
but does not mount its socket into the verifier; the five live-Docker tests and one
OpenTofu test are explicitly excluded by the `integration` marker.

## Running the app locally

**Dev loop (recommended):** mock mode pinned, live code reload, no `.env` needed:

```bash
make dev              # compose + docker-compose.dev.yml override
# WebUI:  http://localhost:5000   (login: admin / nidavellir)
# API:    http://localhost:8000   (header: X-API-Key: dev-insecure-key)
make dev-logs         # tail everything
make dev-down
```

API and WebUI hot-reload when you edit source. The Celery worker doesn't —
after changing task/orchestrator code: `docker compose restart worker`.

**Plain stack** (what production runs, configured via `.env`):

```bash
cp .env.example .env  # MOCK_MODE=true is the default
make up               # docker-compose: redis + orchestrator + worker + webui
# open http://localhost:5000
make down
```

## Branching & commits

- Branch off `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `chore/<topic>`.
- Keep commits focused; write imperative subject lines ("Add lab TTL reaper").
- Open a PR — CI (lint, bandit, tests, docker build) must pass before merge.

## Quality gates (enforced by CI)

| Gate | Tool | Command |
|------|------|---------|
| Lint | ruff | `make lint` |
| Security | bandit | `make security` |
| Hermetic tests | pytest | `make test-unit` |
| Migrations/readiness | Alembic + service clients | `make smoke` |
| Clean SQLite + PostgreSQL | Docker/Python 3.11.14 | `make release-check` |

## Adding tests

- Tests live in `tests/`. `conftest.py` already redirects all runtime state to a
  temp dir and forces mock mode — don't write to the real `data/` or `runs/`.
- Pure-logic tests (database, config) should always run. Tests needing FastAPI
  use `pytest.importorskip("fastapi")` so they skip gracefully if the dep is
  absent locally but run in CI.

## Architecture decisions

Significant changes (new datastore, auth model, provider, etc.) get an ADR in
`docs/adr/`. Copy `docs/adr/0000-template.md`, increment the number, and link it
from your PR.
