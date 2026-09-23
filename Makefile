# Nidavellir developer workflow.
# Run `make help` for the list of targets.

.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE ?= docker compose
ORCH := cyber-range/services/scenario-orchestrator
GATEWAY := cyber-range/services/agent-gateway
HARNESS := cyber-range/services/reference-harness
SCRIPTS := scripts

# Use the project venv's tools when .venv/ exists; fall back to PATH otherwise.
VENV_BIN := .venv/bin
PIP    := $(if $(wildcard $(VENV_BIN)/pip),$(VENV_BIN)/pip,pip)
PYTEST := $(if $(wildcard $(VENV_BIN)/pytest),$(VENV_BIN)/pytest,pytest)
RUFF   := $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
BANDIT := $(if $(wildcard $(VENV_BIN)/bandit),$(VENV_BIN)/bandit,bandit)

.PHONY: help venv install-dev check-python test test-unit test-integration \
	cov lint fmt security smoke check verify-sqlite verify-postgres release-check \
	verify-nv02-live verify-nv03-live verify-nv04-live build-poc-runner up down dev dev-down dev-logs logs clean


help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create .venv/ and install all dev dependencies into it
	python3 -m venv .venv
	$(VENV_BIN)/pip install -r requirements-lock.txt

install-dev: ## Install runtime + dev/test dependencies
	$(PIP) install -r requirements-lock.txt

check-python: ## Refuse unsupported Python versions (the release line is 3.11)
	@python -c 'import platform, sys; print("Python " + platform.python_version()); assert sys.version_info[:2] == (3, 11), "Nidavellir verification requires Python 3.11"'

test: ## Run the test suite (mock mode, no external services)
	MOCK_MODE=true $(PYTEST)

test-unit: ## Run hermetic tests; Docker/OpenTofu integration is explicitly excluded
	MOCK_MODE=true $(PYTEST) -m 'not integration'

test-integration: ## Run Docker/OpenTofu integration tests when their runtimes exist
	MOCK_MODE=true $(PYTEST) -m integration

cov: ## Run tests with coverage report
	MOCK_MODE=true $(PYTEST) --cov=$(ORCH) --cov-report=term-missing

lint: ## Lint Python with ruff
	$(RUFF) check $(ORCH) $(GATEWAY) $(HARNESS) $(SCRIPTS) cyber-range/services/vulnhub-importer cyber-range/webui tests

fmt: ## Auto-format Python with ruff
	$(RUFF) format $(ORCH) $(GATEWAY) $(HARNESS) $(SCRIPTS) cyber-range/services/vulnhub-importer cyber-range/webui tests

security: ## Static security scan with bandit
	$(BANDIT) -r $(ORCH) $(GATEWAY) $(HARNESS) $(SCRIPTS) cyber-range/services/vulnhub-importer cyber-range/webui -x '*/.venv/*,*/venv/*' -ll

smoke: ## Verify migrations plus API, UI and MCP gateway readiness
	python scripts/release-smoke.py

check: check-python lint security test-unit smoke ## Run the supported host gate (requires Python 3.11)

verify-sqlite: check-python lint security test-unit smoke ## Full SQLite release gate inside the pinned environment

verify-postgres: check-python ## Full PostgreSQL test gate (requires DATABASE_URL)
	@python -c 'import os; assert os.environ.get("DATABASE_URL", "").startswith("postgresql"), "verify-postgres requires a PostgreSQL DATABASE_URL"'
	$(MAKE) test-unit

release-check: ## Clean Python 3.11 SQLite + PostgreSQL release gate in Docker
	./scripts/verify-release

verify-nv02-live: ## Isolated real Docker deploy/reset/interruption acceptance
	python3 scripts/verify-nv02-live.py

build-poc-runner: ## Build the trusted, networkless NV-03 Python runner image
	docker build -t nidavellir/poc-runner:py311 $(ORCH)/infra/poc-runner

verify-nv03-live: ## Isolated real Docker confined-PoC acceptance
	python3 scripts/verify-nv03-live.py

verify-nv04-live: ## Isolated real Docker durable-budget and stop acceptance
	python3 scripts/verify-nv04-live.py

up: ## Start the full stack via docker-compose (mock mode by default)
	$(COMPOSE) up -d --build

down: ## Stop and remove containers
	$(COMPOSE) down

DEV_COMPOSE := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml

dev: ## Start the dev stack: mock mode pinned, live code reload, no .env needed
	$(DEV_COMPOSE) up -d --build
	@echo "WebUI: http://localhost:5000 (admin/nidavellir) — API: http://localhost:8000 (X-API-Key: dev-insecure-key)"

dev-down: ## Stop the dev stack
	$(DEV_COMPOSE) down

dev-logs: ## Tail logs from the dev stack
	$(DEV_COMPOSE) logs -f

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

clean: ## Remove caches and local runtime state (DESTRUCTIVE)
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Note: 'runs/', 'data/', 'keys/', 'cache/' left intact. rm -rf them manually to wipe lab state."
