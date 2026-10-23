# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Refusals name the actual problem, and say what to give instead."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.e2e


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["capabilities", "--format", "yaml"], "Error: --format must be text or json, not 'yaml'."),
        (["skill", "--format", "yaml"], "Error: --format must be markdown or skill, not 'yaml'."),
        (["summary", "--format", "yaml"], "Error: --format must be text, json or markdown"),
    ],
)
def test_an_unknown_format_is_refused_in_one_wording(args: list[str], message: str) -> None:
    result = CliRunner().invoke(app, args)

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert message in result.stderr


def test_skill_refuses_json_in_text_because_it_has_no_json() -> None:
    result = CliRunner().invoke(app, ["skill", "--format", "json"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert result.stderr.startswith("Error: --format must be markdown or skill, not 'json'.")


def test_who_changed_in_a_directory_that_is_not_a_repository_says_so(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    result = CliRunner().invoke(app, ["who-changed", "/etc/hosts", "--repo", str(plain)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "is not a valid Git repository" in result.stderr
    assert "outside the repository" not in result.stderr


def test_who_changed_outside_a_repository_still_names_the_repository(repo: Path) -> None:
    result = CliRunner().invoke(app, ["who-changed", "/etc/hosts", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, "positive control: " + result.stderr
    assert "outside the repository" in result.stderr


def test_an_output_with_dot_dot_is_refused_with_the_absolute_path_to_give(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(app, ["generate", "--output", "../report.html"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    expected = os.path.normpath(repo / "../report.html")
    assert f"Give the same place as an absolute path, '{expected}'" in result.stderr


def test_a_path_nothing_in_the_tree_is_named_says_to_check_it(repo: Path) -> None:
    result = CliRunner().invoke(app, ["who-changed", "a.tx", "--repo", str(repo)])

    assert result.exit_code == ExitCode.NEGATIVE
    assert "No commit in the analysis window changed 'a.tx', and nothing by that name" in (
        result.stderr
    )


def test_a_path_in_the_tree_no_commit_in_the_window_changed_is_a_plain_no(repo: Path) -> None:
    """Positive control: the file is there, so the hint would be wrong."""
    result = CliRunner().invoke(
        app, ["who-changed", "a.txt", "--repo", str(repo), "--since", "2999-01-01"]
    )

    assert result.exit_code == ExitCode.NEGATIVE
    assert "No commit in the analysis window changed 'a.txt'." in result.stderr


def test_a_bare_repository_has_no_tree_to_name_the_path_in(repo: Path, tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True)

    result = CliRunner().invoke(app, ["who-changed", "a.tx", "--repo", str(bare)])

    assert result.exit_code == ExitCode.NEGATIVE, result.stderr
    assert "No commit in the analysis window changed 'a.tx'." in result.stderr
