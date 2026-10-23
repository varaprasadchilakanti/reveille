# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The remote URL is read through Git, so a config GitPython cannot parse still reads.

A byte that is not UTF-8 in `.git/config`, and a remote with no `url`, each
stopped every report as "a defect in Reveille" (exit 2).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError

from reveille.adapters.git_reader import GitReader
from reveille.exceptions import RepositoryError

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    identity = ["-c", "user.name=A", "-c", "user.email=a@e.test"]
    subprocess.run(
        ["git", *identity, "commit", "-q", "--allow-empty", "-m", "x"], cwd=path, check=True
    )
    return path


def _config(repo: Path, text: bytes) -> None:
    with (repo / ".git" / "config").open("ab") as handle:
        handle.write(text)


def test_a_byte_that_is_not_utf8_is_shown_not_a_crash(repo: Path) -> None:
    _config(repo, b'[remote "origin"]\n\turl = https://example.test/r\xff.git\n')

    assert GitReader(repo)._resolve_remote_url() == "https://example.test/r�.git"


def test_a_remote_with_no_url_is_passed_over(repo: Path) -> None:
    _config(repo, b'[remote "origin"]\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n')

    assert GitReader(repo)._resolve_remote_url() is None


def test_origin_is_preferred_and_credentials_removed(repo: Path) -> None:
    _config(
        repo,
        b'[remote "first"]\n\turl = https://example.test/first.git\n'
        b'[remote "origin"]\n\turl = https://user:secret@example.test/o.git\n'
        b"\turl = https://example.test/second-url.git\n",
    )

    assert GitReader(repo)._resolve_remote_url() == "https://example.test/o.git"


def test_without_origin_the_first_remote_with_a_url_is_used(repo: Path) -> None:
    _config(
        repo,
        b'[remote "bare"]\n\tfetch = x\n'
        b'[remote "a.b"]\n\turl = https://example.test/dotted.git\n'
        b'[remote "z"]\n\turl = https://example.test/z.git\n',
    )

    assert GitReader(repo)._resolve_remote_url() == "https://example.test/dotted.git"


def test_no_remote_is_none(repo: Path) -> None:
    assert GitReader(repo)._resolve_remote_url() is None


def test_a_config_git_cannot_read_cannot_run(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = GitReader(repo)
    real = reader._git()

    class _Failing:
        def __getattr__(self, name: str) -> Any:
            if name == "config":

                def fail(*args: Any, **kwargs: Any) -> Any:
                    raise GitCommandError("config", 128)

                return fail
            return getattr(real, name)

    monkeypatch.setattr(reader, "_git", lambda extra=(): _Failing())

    with pytest.raises(RepositoryError, match="Git could not read the remotes' URLs"):
        reader._resolve_remote_url()
