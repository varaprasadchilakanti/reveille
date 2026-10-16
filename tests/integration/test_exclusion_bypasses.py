# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Forms of an excluded person's identity that once let them back into the report.

Each was found by running Reveille against a crafted repository: an address in
GitHub's legacy noreply form, a `.mailmap` name with a doubled space, a name
longer than the display cap, and a name carrying an invisible format character.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _repo(path: Path, authors: list[tuple[str, str]], mailmap: str | None = None) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    if mailmap is not None:
        (path / ".mailmap").write_text(mailmap, encoding="utf-8")
    for day, (name, email) in enumerate(authors, start=1):
        (path / "shared.txt").write_text(f"{day}\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "C",
            "GIT_COMMITTER_EMAIL": "c@e.test",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    return path


def _report(repo: Path, value: str) -> str:
    result = CliRunner().invoke(
        app,
        ["generate", "--repo", str(repo), "--format", "json", "--exclude-author", value, "-o", "-"],
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


def test_a_legacy_noreply_address_excludes_the_account(tmp_path: Path) -> None:
    """ADR 0023 counts `ana@users.noreply...` and `123+ana@users.noreply...` as one account."""
    repo = _repo(
        tmp_path / "r",
        [("Ana", "123+ana@users.noreply.github.com"), ("Ben", "ben@e.test")],
    )

    result = CliRunner().invoke(
        app,
        [
            "generate",
            "--repo",
            str(repo),
            "--format",
            "json",
            "-o",
            "-",
            "--exclude-author",
            "ana@users.noreply.github.com",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "noreply" not in result.stdout
    # It matched through the account's other form, so it is not reported as a typo.
    assert "matched no commits" not in result.stderr


def test_a_mailmap_name_with_a_doubled_space_still_reaches_the_person(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path / "r",
        [("Ana Silva", "ana@x.test"), ("Ana Silva", "ana@personal.test"), ("Ben", "ben@e.test")],
        mailmap="Ana  Silva <ana@corp.test> <ana@x.test>\n",
    )

    out = _report(repo, "ana@x.test")

    assert "ana@personal.test" not in out
    assert "ana@corp.test" not in out


def test_a_name_longer_than_the_display_cap_can_be_excluded(tmp_path: Path) -> None:
    long_name = "A" * 300
    repo = _repo(tmp_path / "r", [(long_name, "long@e.test"), ("Ben", "ben@e.test")])

    out = _report(repo, long_name)

    assert "long@e.test" not in out


@pytest.mark.parametrize("invisible", ["\u2060", "\u200d", "\u00ad", "\u180e"])
def test_an_invisible_format_character_does_not_hide_a_name(tmp_path: Path, invisible: str) -> None:
    """Word joiner, zero-width joiner, soft hyphen, Mongolian vowel separator."""
    repo = _repo(
        tmp_path / "r",
        [
            ("Ana Silva", "ana@x.test"),
            (f"Ana Silva{invisible}", "ana2@y.test"),
            ("Ben", "b@e.test"),
        ],
    )

    out = _report(repo, "Ana Silva")

    assert "ana2@y.test" not in out
