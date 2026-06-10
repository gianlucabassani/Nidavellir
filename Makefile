# CyberGuard developer workflow.
# Run `make help` for the list of targets.

.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker-compose
ORCH := cyber-range/services/scenario-orchestrator

.PHONY: help install-dev test cov lint fmt security check up down logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install-dev: ## Install runtime + dev/test dependencies
	pip install -r requirements-dev.txt

test: ## Run the test suite (mock mode, no external services)
	MOCK_MODE=true pytest

cov: ## Run tests with coverage report
	MOCK_MODE=true pytest --cov=$(ORCH) --cov-report=term-missing

lint: ## Lint Python with ruff
	ruff check $(ORCH) cyber-range/services/vulnhub-importer cyber-range/webui tests

fmt: ## Auto-format Python with ruff
	ruff format $(ORCH) cyber-range/services/vulnhub-importer cyber-range/webui tests

security: ## Static security scan with bandit
	bandit -r $(ORCH) cyber-range/services/vulnhub-importer cyber-range/webui -ll

check: lint security test ## Run lint + security + tests (CI parity)

up: ## Start the full stack via docker-compose (mock mode by default)
	$(COMPOSE) up -d --build

down: ## Stop and remove containers
	$(COMPOSE) down

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

clean: ## Remove caches and local runtime state (DESTRUCTIVE)
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Note: 'runs/', 'data/', 'keys/', 'cache/' left intact. rm -rf them manually to wipe lab state."
