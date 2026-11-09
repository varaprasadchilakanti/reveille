# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`.github/scripts/changed_code.py` tells CI whether a pull request changes code.

A wrong `false` would skip tests on a change that needs them, so every doubt answers `true`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "changed_code.py"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("a\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "base")
    return path


def _answer(repo: Path, base: str, output: Path | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    if output is not None:
        env["GITHUB_OUTPUT"] = str(output)
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), base],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _change(repo: Path, *paths: str) -> str:
    base = _git(repo, "rev-parse", "HEAD")
    for name in paths:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("changed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return base


def test_documentation_alone_is_not_code(repo: Path, tmp_path: Path) -> None:
    base = _change(
        repo,
        "README.md",
        "docs/adr/0099-x.md",
        "docs/images/a.svg",
        "docs/images/a.png",
        "llms.txt",
    )
    output = tmp_path / "out"

    assert _answer(repo, base, output) == "code=false"
    assert output.read_text(encoding="utf-8") == "code=false\n"


@pytest.mark.parametrize(
    "path",
    [
        "src/reveille/cli.py",
        "docs/images/make_sample_repository.py",
        "pyproject.toml",
        "src/reveille/templates/note.md",
        "tests/fixtures/chart.svg",
        "src/llms.txt",
    ],
)
def test_anything_else_is_code(repo: Path, path: str) -> None:
    base = _change(repo, "README.md", path)

    assert _answer(repo, base) == "code=true"


def test_code_renamed_to_markdown_is_code(repo: Path) -> None:
    (repo / "x.py").write_text("print('a long enough line to be found as a rename')\n", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "code")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "mv", "x.py", "x.md")
    _git(repo, "commit", "-qm", "rename")
    # Positive control: Git's default diff lists only the new name.
    assert _git(repo, "diff", "--name-only", base, "HEAD") == "x.md"

    assert _answer(repo, base) == "code=true"


def test_a_base_git_cannot_read_runs_everything(repo: Path) -> None:
    assert _answer(repo, "0" * 40) == "code=true"


def test_no_base_cannot_run(repo: Path) -> None:
    done = subprocess.run(
        [sys.executable, str(_SCRIPT)], cwd=repo, capture_output=True, text=True, check=False
    )

    assert done.returncode == 2
