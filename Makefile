# ==================================================================
# Reveille -- Git Repository Intelligence
# ==================================================================

.DEFAULT_GOAL := help

.PHONY: help install lint format fix typecheck precommit check-lock check-lock-sync check-licence check-version \
	    check-packaging test test-unit \
	    test-integration test-e2e coverage ci build sbom publish-test \
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

check-lock:  ## Assert poetry.lock is valid TOML before anything tries to install from it
	@test -f poetry.lock || { echo "poetry.lock is missing."; exit 1; }
	@if ! ERR=$$(python3 -c "import tomllib; tomllib.load(open('poetry.lock','rb'))" 2>&1); then \
		echo "poetry.lock is not valid TOML:"; \
		echo "  $$(echo "$$ERR" | tail -1)"; \
		echo ""; \
		echo "A generated lock file must never be hand-merged: 'keep both sides'"; \
		echo "silently duplicates keys. Regenerate it with the tool that owns it:"; \
		echo "    poetry lock --no-update"; \
		exit 1; \
	fi
	@echo "poetry.lock is valid TOML"

# Distinct from check-lock, and deliberately so. check-lock asks whether the
# file can be parsed at all, using only the standard library, so it can run
# before anything installs. This asks the different question closed by audit
# finding #20: whether the lock still agrees with pyproject.toml. A lock can be
# perfectly valid TOML and still describe a dependency set nobody asked for.
#
# `poetry lock --check` rather than `poetry check --lock`: the latter also
# validates Trove classifiers against the list bundled with Poetry 1.8.2, which
# predates `Programming Language :: Python :: 3.14` and so fails for a reason
# that has nothing to do with the lock. Revisit when the pinned Poetry moves.
check-lock-sync:  ## Assert poetry.lock still agrees with pyproject.toml
	@poetry lock --check

check-licence:  ## Assert LICENSE, pyproject.toml and reveille.__licence__ agree
	@TOML_LIC=$$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['tool']['poetry']['license'])") \
		|| { echo "check-licence: could not read the licence from pyproject.toml"; exit 1; }; \
	CODE_LIC=$$(poetry run python -c "import reveille; print(reveille.__licence__)") \
		|| { echo "check-licence: could not read reveille.__licence__"; exit 1; }; \
	if [ -z "$$TOML_LIC" ] || [ -z "$$CODE_LIC" ]; then \
		echo "check-licence: a licence value was empty (pyproject='$$TOML_LIC', code='$$CODE_LIC')."; \
		echo "Refusing to compare two blanks and call it agreement."; \
		exit 1; \
	fi; \
	if [ "$$TOML_LIC" != "$$CODE_LIC" ]; then \
		echo "Licence mismatch: pyproject.toml=$$TOML_LIC, __init__.py=$$CODE_LIC"; \
		exit 1; \
	fi; \
	if ! grep -q "Apache License" LICENSE || ! grep -q "Version 2.0, January 2004" LICENSE; then \
		echo "LICENSE does not contain the Apache License 2.0 text"; \
		exit 1; \
	fi; \
	echo "Licence declarations agree: $$TOML_LIC"

check-packaging:  ## Assert the PEP 561 py.typed marker ships in the built distributions
	@rm -rf dist
	@poetry build -q
	@poetry run python -c "import glob, sys, tarfile, zipfile; w = sorted(glob.glob('dist/*.whl'))[-1]; s = sorted(glob.glob('dist/*.tar.gz'))[-1]; missing = [k for k, ok in (('wheel', 'reveille/py.typed' in zipfile.ZipFile(w).namelist()), ('sdist', any(n.endswith('reveille/py.typed') for n in tarfile.open(s).getnames()))) if not ok]; sys.exit('py.typed missing from: ' + ', '.join(missing)) if missing else None"
	@rm -rf dist
	@echo "py.typed marker present in wheel and sdist"

check-version:  ## Assert pyproject.toml version matches reveille.__version__
	@TOML_VER=$$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['tool']['poetry']['version'])") \
		|| { echo "check-version: could not read the version from pyproject.toml"; exit 1; }; \
	CODE_VER=$$(poetry run python -c "import reveille; print(reveille.__version__)") \
		|| { echo "check-version: could not read reveille.__version__"; exit 1; }; \
	if [ -z "$$TOML_VER" ] || [ -z "$$CODE_VER" ]; then \
		echo "check-version: a version value was empty (pyproject='$$TOML_VER', code='$$CODE_VER')."; \
		echo "Refusing to compare two blanks and call it agreement."; \
		exit 1; \
	fi; \
	if [ "$$TOML_VER" != "$$CODE_VER" ]; then \
		echo "Version mismatch: pyproject.toml=$$TOML_VER, __init__.py=$$CODE_VER"; \
		exit 1; \
	fi; \
	echo "Version declarations agree: $$TOML_VER"

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
	$(MAKE) check-lock
	$(MAKE) check-lock-sync
	$(MAKE) check-version
	$(MAKE) check-licence
	$(MAKE) check-packaging
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test

# ------------------------------------------------------------------
# Build & Publish
# ------------------------------------------------------------------

build:  ## Build the distribution packages
	poetry build

# The SBOM generator is deliberately not a project dependency. It reads
# pyproject.toml and poetry.lock as files, so it needs no access to the
# project environment -- and keeping it out means the tool that describes
# our dependency graph is not itself a member of it. It lives in a
# throwaway venv instead, pinned to the same version CI uses.
SBOM_TOOL_VERSION := 7.3.1
SBOM_VENV := .tool-venvs/sbom

$(SBOM_VENV):
	@python3 -m venv $(SBOM_VENV)
	@$(SBOM_VENV)/bin/pip install --quiet --disable-pip-version-check \
		cyclonedx-bom==$(SBOM_TOOL_VERSION)

sbom: $(SBOM_VENV)  ## Generate a CycloneDX SBOM of the runtime dependency graph
	@mkdir -p dist
	@VER=$$(poetry version --short); \
	$(SBOM_VENV)/bin/cyclonedx-py poetry --no-dev --output-reproducible \
		--of JSON -o "dist/reveille-$$VER-sbom.cdx.json" . && \
	echo "SBOM written to dist/reveille-$$VER-sbom.cdx.json"

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
