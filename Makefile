# CyberGuard developer workflow.
# Run `make help` for the list of targets.

.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker-compose
ORCH := cyber-range/services/scenario-orchestrator
GATEWAY := cyber-range/services/agent-gateway

# Use the project venv's tools when .venv/ exists; fall back to PATH otherwise.
VENV_BIN := .venv/bin
PIP    := $(if $(wildcard $(VENV_BIN)/pip),$(VENV_BIN)/pip,pip)
PYTEST := $(if $(wildcard $(VENV_BIN)/pytest),$(VENV_BIN)/pytest,pytest)
RUFF   := $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
BANDIT := $(if $(wildcard $(VENV_BIN)/bandit),$(VENV_BIN)/bandit,bandit)

.PHONY: help venv install-dev test cov lint fmt security check up down dev dev-down dev-logs logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create .venv/ and install all dev dependencies into it
	python3 -m venv .venv
	$(VENV_BIN)/pip install -r requirements-dev.txt

install-dev: ## Install runtime + dev/test dependencies
	$(PIP) install -r requirements-dev.txt

test: ## Run the test suite (mock mode, no external services)
	MOCK_MODE=true $(PYTEST)

cov: ## Run tests with coverage report
	MOCK_MODE=true $(PYTEST) --cov=$(ORCH) --cov-report=term-missing

lint: ## Lint Python with ruff
	$(RUFF) check $(ORCH) $(GATEWAY) cyber-range/services/vulnhub-importer cyber-range/webui tests

fmt: ## Auto-format Python with ruff
	$(RUFF) format $(ORCH) $(GATEWAY) cyber-range/services/vulnhub-importer cyber-range/webui tests

security: ## Static security scan with bandit
	$(BANDIT) -r $(ORCH) $(GATEWAY) cyber-range/services/vulnhub-importer cyber-range/webui -ll

check: lint security test ## Run lint + security + tests (CI parity)

up: ## Start the full stack via docker-compose (mock mode by default)
	$(COMPOSE) up -d --build

down: ## Stop and remove containers
	$(COMPOSE) down

DEV_COMPOSE := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml

dev: ## Start the dev stack: mock mode pinned, live code reload, no .env needed
	$(DEV_COMPOSE) up -d --build
	@echo "WebUI: http://localhost:5000 (admin/cyberguard) — API: http://localhost:8000 (X-API-Key: dev-insecure-key)"

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
