# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`--format markdown` for state, brief and summary: repository text stays literal.

The output is pasted into an issue, a pull request or a CI job summary, where
a path, branch or tag name could otherwise add a heading, a link or HTML.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    for name in ("a.txt", "b.txt"):
        (path / name).write_text(name, encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", name)
    _git(path, "tag", "v1", "HEAD~1")
    return path


def _md(repo: Path, *args: str) -> str:
    result = CliRunner().invoke(app, [*args, "--repo", str(repo), "--format", "markdown"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    ("args", "heading", "notice"),
    [
        (["state"], "### State: `r`", "Read from the repository"),
        (["brief", "--from", "v1"], "### Brief: `r`", "Computed from Git history"),
        (["summary"], "### Summary: `r`", "Computed from Git history"),
    ],
)
def test_each_command_renders(repo: Path, args: list[str], heading: str, notice: str) -> None:
    out = _md(repo, *args)

    assert out.startswith(heading)
    assert f"\n> {notice}" in out
    assert len(out.encode()) < 2048
    assert "Ana" not in out and "ana@" not in out


def test_a_hostile_file_name_stays_inside_its_code_span(repo: Path) -> None:
    (repo / "x`y\n# Pwned <b>[l](http:x)|.txt").write_text("x", encoding="utf-8")

    out = _md(repo, "state")

    assert "\n# Pwned" not in out, "a newline in a name must not start a Markdown line"
    assert "``x`y\\n# Pwned <b>[l](http:x)|.txt``" in out


def test_a_tag_with_a_backtick_stays_inside_its_code_span(repo: Path) -> None:
    _git(repo, "tag", "v2`<b>x</b>")

    out = _md(repo, "brief", "--from", "v1")

    assert "``v2`<b>x</b>``" in out


def test_who_changed_offers_no_markdown(repo: Path) -> None:
    result = CliRunner().invoke(
        app, ["who-changed", "a.txt", "--repo", str(repo), "--format", "markdown"]
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "text or json" in result.stderr
