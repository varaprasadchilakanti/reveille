"""Counts of one read as one: "1 day", "1 line", not "1 days", "1 lines".

The 0.9.0 changelog said these were fixed; a verification pass found the
summary's quiet run and the lock-file caption still printing the plural.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Commits on 1 and 3 March, so one quiet day; a lock file of one line."""
    path = tmp_path_factory.mktemp("singular") / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day, name in ((1, "poetry.lock"), (3, "a.py")):
        (path / name).write_text("x\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Ana",
            "GIT_AUTHOR_EMAIL": "ana@e.test",
            "GIT_COMMITTER_NAME": "Ana",
            "GIT_COMMITTER_EMAIL": "ana@e.test",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    return path


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def _out(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", result.stdout))


@pytest.mark.integration
def test_the_summary_says_one_day_and_two_decimal_places(repo: Path) -> None:
    out = _out("summary", "--repo", str(repo), "--deterministic")

    assert "Gini 0.00, longest quiet run 1 day." in out


@pytest.mark.integration
def test_the_lock_file_caption_says_one_line(repo: Path) -> None:
    out = _out("generate", "--repo", str(repo), "--deterministic", "-o", "-")

    assert "1 lock file (1 line changed) is left out" in out
