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

## Workflow: issue → branch → PR

Every change, including the maintainer's own, follows one path:

1. **Issue.** Open an issue (bug report or feature/task form) that states the
   problem and the acceptance. Reference the `TODO.md` NV ID, ROADMAP item or ADR when one
   applies. Large items are split into issues that can each land on their own.
2. **Branch.** Branch from an up-to-date `main` as `<type>/<issue#>-<slug>`, where
   `<type>` is `feat`, `fix`, `docs`, `ci`, `chore` or `refactor`.
   Example: `fix/1-fresh-clone-quickstart`.
3. **Commits.** Use focused commits with
   [Conventional Commit](https://www.conventionalcommits.org/) subjects
   (`fix(dev): …`, `feat(arenas): …`). For material changes, the body records the outcome,
   the verification, unresolved risks and the next step (see `AGENTS.md`).
4. **Pull request.** One PR per issue, with `Closes #N` in the description; the template
   asks for verification and risks. Keep a PR focused on its issue and open a new issue
   for anything you discover along the way.
5. **Merge.** `main` is protected: a PR can merge only when CI (lint, bandit, tests on
   SQLite and PostgreSQL, image build, fresh-clone quickstart) and the Guard (secrets,
   local paths) are green. History stays linear (squash or rebase merges).

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
