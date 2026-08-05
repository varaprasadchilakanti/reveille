# ==================================================================
# Reveille -- Git Repository Intelligence
# ==================================================================

.DEFAULT_GOAL := help

.PHONY: help install lint format fix typecheck precommit check-packaging test test-unit \
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

check-packaging:  ## Assert the PEP 561 py.typed marker ships in the built distributions
	@rm -rf dist
	@poetry build -q
	@poetry run python -c "import glob, sys, tarfile, zipfile; w = sorted(glob.glob('dist/*.whl'))[-1]; s = sorted(glob.glob('dist/*.tar.gz'))[-1]; missing = [k for k, ok in (('wheel', 'reveille/py.typed' in zipfile.ZipFile(w).namelist()), ('sdist', any(n.endswith('reveille/py.typed') for n in tarfile.open(s).getnames()))) if not ok]; sys.exit('py.typed missing from: ' + ', '.join(missing)) if missing else None"
	@rm -rf dist
	@echo "py.typed marker present in wheel and sdist"

check-version:  ## Assert pyproject.toml version matches reveille.__version__
	@TOML_VER=$$(poetry version --short); \
	CODE_VER=$$(poetry run python -c "import reveille; print(reveille.__version__)"); \
	if [ "$$TOML_VER" != "$$CODE_VER" ]; then \
		echo "Version mismatch: pyproject.toml=$$TOML_VER, __init__.py=$$CODE_VER"; \
		exit 1; \
	fi

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

precommit:  ## Run all pre-commit hooks against every tracked file
	poetry run pre-commit run --all-files

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
	$(MAKE) check-version
	$(MAKE) check-packaging
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
