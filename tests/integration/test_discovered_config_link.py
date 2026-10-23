# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A discovered reveille.toml that is a symbolic link is not followed.

Git checks a committed link out as a link, so a repository's `reveille.toml`
could name any file on the machine running Reveille; that file's report title
reached the report, and a refused value reached stderr.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.config import read_config_file
from reveille.exceptions import ConfigurationError

pytestmark = pytest.mark.integration

_ELSEWHERE = '[report]\ntitle = "TITLE-FROM-ELSEWHERE"\n'


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository, the working directory, beside a file it does not hold."""
    path = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    identity = ["-c", "user.name=A", "-c", "user.email=a@e.test"]
    subprocess.run(
        ["git", *identity, "commit", "-q", "--allow-empty", "-m", "a"], cwd=path, check=True
    )
    (tmp_path / "elsewhere.toml").write_text(_ELSEWHERE, encoding="utf-8")
    monkeypatch.chdir(path)
    return path


def _link(clone: Path, target: Path) -> None:
    try:
        (clone / "reveille.toml").symlink_to(target)
    except OSError:
        pytest.skip("this system does not let the test make a symbolic link")


def _generate(clone: Path, *args: str) -> tuple[int, str, str]:
    out = clone.parent / "report.html"
    result = CliRunner().invoke(app, ["generate", "-q", "-o", str(out), *args])
    written = out.read_text(encoding="utf-8") if out.exists() else ""
    return result.exit_code, result.stderr, written


@pytest.mark.parametrize("target", ["elsewhere.toml", "missing.toml"])
def test_a_discovered_link_is_refused_wherever_it_points(clone: Path, target: str) -> None:
    _link(clone, clone.parent / target)

    code, err, written = _generate(clone)

    assert code == ExitCode.CANNOT_RUN
    assert "auto-discovered reveille.toml is a symbolic link, so it is not read" in err
    assert "give it with --config" in err
    assert written == ""


def test_the_same_link_given_with_config_is_read(clone: Path) -> None:
    """Positive control: a file the user names is the user's choice."""
    _link(clone, clone.parent / "elsewhere.toml")

    code, err, written = _generate(clone, "--config", "reveille.toml")

    assert code == ExitCode.SUCCESS, err
    assert "TITLE-FROM-ELSEWHERE" in written


def test_a_discovered_regular_file_is_read(clone: Path) -> None:
    """Positive control: only the link is refused."""
    (clone / "reveille.toml").write_text(_ELSEWHERE, encoding="utf-8")

    code, err, written = _generate(clone)

    assert code == ExitCode.SUCCESS, err
    assert "TITLE-FROM-ELSEWHERE" in written


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="needs O_NOFOLLOW")
def test_a_link_put_in_place_after_the_check_is_refused_when_opened(clone: Path) -> None:
    """The open refuses it too, so a link swapped in after the check is not read."""
    _link(clone, clone.parent / "elsewhere.toml")

    with pytest.raises(ConfigurationError, match="is a symbolic link, which is not followed"):
        read_config_file(Path("reveille.toml"), follow_links=False)
    settings, _ = read_config_file(Path("reveille.toml"))
    assert settings["title"] == "TITLE-FROM-ELSEWHERE", "positive control: followed when asked"
