# ==================================================================
# Reveille -- Git Repository Intelligence
# ==================================================================

.DEFAULT_GOAL := help

.PHONY: help install lint format fix typecheck test test-unit \
        test-integration test-e2e coverage ci build publish-test \
        publish clean

# ------------------------------------------------------------------
# Help
# ------------------------------------------------------------------

help:  ## Display available targets
	@echo "\nReveille -- Available Commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk \
	'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

install:  ## Install all dependencies including dev group
	poetry install

# ------------------------------------------------------------------
# Code Quality
# ------------------------------------------------------------------

lint:  ## Run ruff lint checks
	poetry run ruff check src tests

format:  ## Format code with ruff formatter
	poetry run ruff format src tests

fix:  ## Auto-fix lint issues with ruff
	poetry run ruff check src tests --fix

typecheck:  ## Run mypy in strict mode
	poetry run mypy src

# ------------------------------------------------------------------
# Testing
# ------------------------------------------------------------------

test:  ## Run the full test suite (parallel, no coverage instrumentation)
    poetry run pytest -n auto

test-unit:  ## Run unit tests only
	poetry run pytest tests/unit -m unit

test-integration:  ## Run integration tests only
	poetry run pytest tests/integration -m integration

test-e2e:  ## Run end-to-end tests only
	poetry run pytest tests/e2e -m e2e

coverage:  ## Generate HTML and terminal coverage report
    poetry run pytest -n auto --cov=reveille --cov-report=term-missing --cov-report=html
    @echo "HTML coverage report: htmlcov/index.html"

# ------------------------------------------------------------------
# CI
# ------------------------------------------------------------------

ci:  ## Full CI workflow: lint, typecheck, test
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test

# ------------------------------------------------------------------
# Build & Publish
# ------------------------------------------------------------------

build:  ## Build the distribution packages
	poetry build

publish-test:  ## Publish to TestPyPI
	poetry publish --repository testpypi

publish:  ## Publish to PyPI (requires credentials)
	poetry publish

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------

clean:  ## Remove build artefacts and cache directories
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .coverage coverage.xml htmlcov/ dist/ build/
