# Contributing to CyberGuard

Thanks for helping build CyberGuard. This guide gets you from clone to green tests.

## Development setup

```bash
# 1. Clone & enter
git clone https://github.com/gianlucabassani/CyberGuard.git
cd CyberGuard

# 2. Create a virtualenv
python3 -m venv .venv && source .venv/bin/activate

# 3. Install runtime + dev dependencies
make install-dev      # == pip install -r requirements-dev.txt

# 4. Run the checks
make check            # lint + security scan + tests
```

You do **not** need OpenStack or Redis to develop or run the test suite — the
tests run in `MOCK_MODE=true` and stub the task queue.

## Running the app locally

**Dev loop (recommended):** mock mode pinned, live code reload, no `.env` needed:

```bash
make dev              # compose + docker-compose.dev.yml override
# WebUI:  http://localhost:5000   (login: admin / cyberguard)
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
| Tests | pytest | `make test` |

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
