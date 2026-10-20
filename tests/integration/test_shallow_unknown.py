# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""When Git cannot say whether a clone is shallow, Reveille does not guess "no".

`is_shallow` returned False on any error, so a shallow clone's figures could be
reported as the whole history, with no notice.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError

from reveille.adapters.git_reader import GitReader, RepositoryError

pytestmark = pytest.mark.integration


@pytest.fixture
def reader(tmp_path: Path) -> GitReader:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=A",
            "-c",
            "user.email=a@e.test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "a",
        ],
        cwd=tmp_path,
        check=True,
    )
    return GitReader(tmp_path)


class _Answering:
    """Git, except that `rev-parse --is-shallow-repository` gives `answer` or fails."""

    def __init__(self, real: Any, answer: str | None) -> None:
        self._real, self._answer = real, answer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def rev_parse(self, *args: str, **kwargs: Any) -> Any:
        if "--is-shallow-repository" not in args:
            return self._real.rev_parse(*args, **kwargs)
        if self._answer is None:
            raise GitCommandError(["git", "rev-parse"], 128, b"fatal: broken")
        return self._answer


def _with_git(reader: GitReader, monkeypatch: pytest.MonkeyPatch, answer: str | None) -> None:
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda: _Answering(real, answer))


def test_a_clone_that_is_not_shallow_says_so(reader: GitReader) -> None:
    assert reader.is_shallow() is False  # positive control: the real answer


@pytest.mark.parametrize(("answer", "says"), [(None, "fatal: broken"), ("", "it answered ''")])
def test_no_answer_is_refused_not_read_as_no(
    reader: GitReader, monkeypatch: pytest.MonkeyPatch, answer: str | None, says: str
) -> None:
    _with_git(reader, monkeypatch, answer)

    with pytest.raises(
        RepositoryError, match="could not say whether this is a shallow clone"
    ) as raised:
        reader.is_shallow()

    assert says in str(raised.value)


def test_a_shallow_answer_is_read(reader: GitReader, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_git(reader, monkeypatch, "true\n")

    assert reader.is_shallow() is True
