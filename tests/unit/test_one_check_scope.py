# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""CI, the pre-commit hooks and `make` check one list of paths.

CI ran ruff over `src tests` and mypy over `src`, the hooks did the same, and `make lint` added
`scripts`; `.github/scripts` and `docs/images` were checked by none. Now the Makefile names the
paths once and the others run its targets.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
# A command line that runs either tool; a job name such as "Lint (ruff)" is not one.
_CALLS = re.compile(r"\b(?:ruff (?:check|format)|mypy)\s")


def _commands(path: str) -> list[str]:
    """Each line of a YAML file that is not a comment, a job or step name, or an `id:`."""
    text = (_ROOT / path).read_text(encoding="utf-8")
    skipped = ("#", "name:", "- name:", "id:", "- id:")
    return [line.strip() for line in text.splitlines() if not line.strip().startswith(skipped)]


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", ".pre-commit-config.yaml"])
def test_ruff_and_mypy_run_only_through_make(path: str) -> None:
    assert [line for line in _commands(path) if _CALLS.search(line)] == []


def test_ci_and_the_hooks_call_the_make_targets() -> None:
    assert {"run: make lint", "run: make format-check", "run: make typecheck"} <= set(
        _commands(".github/workflows/ci.yml")
    )
    assert {"entry: make fix", "entry: make format", "entry: make typecheck"} <= set(
        _commands(".pre-commit-config.yaml")
    )


def test_every_tracked_python_directory_is_linted() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    listed = re.search(r"^LINT_PATHS := (.+)$", makefile, re.MULTILINE)
    assert listed is not None
    paths = listed.group(1).split()
    listing = subprocess.run(
        ["git", "ls-files", "--", "*.py"], cwd=_ROOT, check=True, capture_output=True, text=True
    )
    tracked = {(_ROOT / name).parent for name in listing.stdout.split("\n") if name}

    unlinted = sorted(
        str(directory.relative_to(_ROOT))
        for directory in tracked
        if not any(directory.is_relative_to(_ROOT / path) for path in paths)
    )

    assert unlinted == []


def _make_ci_recipe() -> list[str]:
    """The lines of the `ci` target's recipe in the Makefile."""
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    # A recipe runs to the next line that starts with neither a tab nor nothing at all.
    recipe = re.search(r"^ci:.*\n((?:\t.*\n|\n)+)", makefile, re.MULTILINE)
    assert recipe is not None, "the Makefile has no `ci` target"
    return [line.strip() for line in recipe.group(1).split("\n") if line.strip()]


def test_ci_runs_the_make_targets_make_ci_runs() -> None:
    # CI lists its steps itself, to spread them over jobs; this keeps the two lists one list.
    in_ci = {
        line.removeprefix("run: make ")
        for line in _commands(".github/workflows/ci.yml")
        if line.startswith("run: make ")
    }
    in_make_ci = {
        line.removeprefix("$(MAKE) ") for line in _make_ci_recipe() if line.startswith("$(MAKE) ")
    }

    assert in_ci == in_make_ci


def test_ci_and_make_ci_measure_coverage_of_the_same_package() -> None:
    def coverage(lines: list[str]) -> list[str]:
        return [
            w for line in lines if "pytest" in line for w in line.split() if w.startswith("--cov=")
        ]

    assert coverage(_make_ci_recipe()) == ["--cov=reveille"]
    assert coverage(_commands(".github/workflows/ci.yml")) == ["--cov=reveille"]
