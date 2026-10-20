# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A bare repository refused by `safe.bareRepository=explicit` is said to be refused for that.

Reveille said the repository's configuration "does not say it is bare (core.bare is not
true)", of a repository whose core.bare is true.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=source,
        check=True,
    )
    bare = tmp_path / "download" / "embedded.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(bare)], check=True)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.bareRepository")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "explicit")
    return bare


@pytest.mark.parametrize("command", ["summary", "state", "brief"])
def test_the_refusal_names_the_setting(bare: Path, command: str) -> None:
    result = CliRunner().invoke(app, [command, "--repo", str(bare)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "safe.bareRepository setting is 'explicit'" in result.stderr
    assert "core.bare is not true" not in result.stderr


def test_without_the_setting_the_bare_repository_is_read(
    bare: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GIT_CONFIG_COUNT")

    result = CliRunner().invoke(app, ["summary", "--repo", str(bare)])

    assert result.exit_code == ExitCode.SUCCESS, "positive control: " + result.stderr
