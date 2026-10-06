"""The interface an assistant uses (ADR 0015).

An assistant's stdout is its input: anything on it besides the document it
asked for -- a progress line, a "Report written to" -- is a parse error or
a polluted context.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("agent_repo")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day, (name, email, file) in enumerate(
        [
            ("Zoe", "zoe@e.test", "src/core/a.py"),
            ("Amir", "amir@e.test", "src/core/b.py"),
            ("Zoe", "zoe@e.test", "docs/x.md"),
            ("dependabot[bot]", "bot@e.test", "src/core/a.py"),
        ],
        start=1,
    ):
        target = path / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{day}\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    return path


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run from an empty directory: if `-o -` were ever taken as a file name
    again, the file lands there rather than in the working tree."""
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.e2e
class TestOutputToStdout:
    def test_json_is_the_only_thing_on_stdout(self, repo: Path, tmp_path: Path) -> None:
        code, out, err = _run(
            "generate", "--repo", str(repo), "--format", "json", "--deterministic", "-o", "-"
        )

        assert code == ExitCode.SUCCESS, err
        assert json.loads(out)["metadata"]["total_commits"] == 4
        assert "Report written to" not in out
        assert not list(tmp_path.iterdir()), "no file is written"

    def test_csv_on_stdout_has_no_byte_order_mark(self, repo: Path) -> None:
        code, out, _ = _run("generate", "--repo", str(repo), "--format", "csv", "-o", "-")

        assert code == ExitCode.SUCCESS
        assert not out.startswith("﻿")
        rows = list(csv.DictReader(io.StringIO(out)))
        assert {r["email"] for r in rows} == {"zoe@e.test", "amir@e.test", "bot@e.test"}

    def test_html_on_stdout(self, repo: Path) -> None:
        code, out, _ = _run("generate", "--repo", str(repo), "-o", "-")

        assert code == ExitCode.SUCCESS
        assert out.lstrip().lower().startswith("<!doctype html>")


@pytest.mark.e2e
class TestSummary:
    def test_json_answers_the_repository_questions(self, repo: Path) -> None:
        code, out, err = _run("summary", "--repo", str(repo), "--format", "json", "--deterministic")

        assert code == ExitCode.SUCCESS, err
        document = json.loads(out)
        assert document["document"] == "summary"
        assert document["totals"] == {"commits": 4, "authors": 3, "commits_with_co_authors": 0}
        assert set(document["measures"]) == {
            "gini_coefficient",
            "commit_concentration",
            "longest_quiet_run_days",
            "days_since_last_commit",
        }
        assert "check before relying on it" in document["notice"]

    def test_it_names_nobody(self, repo: Path) -> None:
        for fmt in ("json", "text"):
            _, out, _ = _run("summary", "--repo", str(repo), "--format", fmt)
            for identity in ("Zoe", "Amir", "zoe@", "amir@", "dependabot", "bot@"):
                assert identity not in out, f"{identity!r} in the {fmt} summary"

    def test_it_is_small(self, repo: Path) -> None:
        _, out, _ = _run("summary", "--repo", str(repo), "--format", "json")

        assert len(out.encode()) < 4096

    def test_an_empty_window_is_a_negative_answer(self, repo: Path) -> None:
        code, out, _ = _run("summary", "--repo", str(repo), "--since", "2030-01-01")

        assert code == ExitCode.NEGATIVE
        assert out == ""

    def test_an_unknown_format_cannot_run(self, repo: Path) -> None:
        code, _, err = _run("summary", "--repo", str(repo), "--format", "yaml")

        assert code == ExitCode.CANNOT_RUN
        assert "text or json" in err
