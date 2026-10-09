"""Lock files: one rule for both file charts.

The hotspot ranking leaves them out and the type breakdown keeps their
churn. Before this, the ranking's caption said only "Lock files are left
out", without saying how much, and the type breakdown counted
`package-lock.json` as hand-written `.json`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


def _repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for name, text in files.items():
        (path / name).write_text(text, encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
        "GIT_AUTHOR_DATE": "2026-03-01T10:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-03-01T10:00:00+00:00",
    }
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=path, check=True, env=env)
    return path


def _html(repo: Path) -> str:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--deterministic", "-o", "-"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


def _extensions(html: str) -> dict[str, int]:
    spec = re.search(r'id="spec-extensions">\s*(.*?)\s*</script>', html, re.DOTALL)
    assert spec, "the type breakdown is missing"
    trace = json.loads(spec.group(1))["data"][0]
    return dict(zip(trace["x"], trace["y"], strict=True))


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.mark.integration
class TestLockFiles:
    def test_the_ranking_says_what_it_left_out(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path / "r", {"package-lock.json": "x\n" * 30, "a.py": "1\n"})
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html(repo)))

        assert (
            "1 lock file (30 lines changed) is left out and counted under Change by File Type."
            in text
        )

    def test_the_breakdown_does_not_count_a_lock_file_as_json(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path / "r",
            {"package-lock.json": "x\n" * 30, "tsconfig.json": "{}\n", "a.py": "1\n"},
        )

        assert _extensions(_html(repo)) == {"lock files": 30, ".json": 1, ".py": 1}

    def test_without_lock_files_nothing_is_said(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path / "r", {"a.py": "1\n", "b.md": "x\n"})

        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html(repo)))
        # A bool, not `not in text`: on failure pytest would diff the whole page.
        stated = "left out and counted under Change by File Type" in text
        assert not stated
