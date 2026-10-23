# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A path inside a submodule that has no files here is not "changed by no commit".

Cloned without `--recurse-submodules`, a submodule is an empty directory; in a
bare superproject it is nothing at all. Either way the working-tree check found
no other repository, and `who-changed` answered "no" (exit 1) for history this
repository does not hold. The commit's tree records the submodule; it is read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError
from typer.testing import CliRunner

from reveille.adapters.git_reader import GitReader
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


_SETTINGS = ["-c", "user.name=A", "-c", "user.email=a@e.test", "-c", "protocol.file.allow=always"]


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", *_SETTINGS, *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def layouts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("submodule")
    _git("init", "-q", "-b", "main", str(root / "inner"))
    (root / "inner" / "f.txt").write_text("f", encoding="utf-8")
    _git("add", "f.txt", cwd=root / "inner")
    _git("commit", "-qm", "inner", cwd=root / "inner")
    _git("init", "-q", "-b", "main", str(root / "super"))
    (root / "super" / "top.txt").write_text("t", encoding="utf-8")
    _git("add", "top.txt", cwd=root / "super")
    _git("commit", "-qm", "top", cwd=root / "super")
    _git("submodule", "-q", "add", str(root / "inner"), "lib/sub", cwd=root / "super")
    _git("commit", "-qm", "sub", cwd=root / "super")
    _git("clone", "-q", str(root / "super"), str(root / "clone"))
    _git("clone", "-q", "--bare", str(root / "super"), str(root / "bare.git"))
    return root


def _who(repo: Path, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["who-changed", *args, "--repo", str(repo)])
    return result.exit_code, " ".join(result.stderr.split())


@pytest.mark.parametrize("layout", ["clone", "bare.git"])
def test_a_path_inside_it_cannot_be_answered_here(layouts: Path, layout: str) -> None:
    assert not any((layouts / "clone" / "lib" / "sub").iterdir()), "not checked out"

    code, stderr = _who(layouts / layout, "lib/sub/f.txt")

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "'lib/sub/f.txt' is inside 'lib/sub', a submodule" in stderr
    assert "not checked out here" in stderr


@pytest.mark.parametrize("layout", ["clone", "bare.git"])
def test_the_submodule_itself_is_answered_from_this_history(layouts: Path, layout: str) -> None:
    code, stderr = _who(layouts / layout, "lib/sub")

    assert code == ExitCode.SUCCESS, stderr


@pytest.mark.parametrize("layout", ["clone", "bare.git"])
@pytest.mark.parametrize("path", ["lib/other.txt", "lib/x/y.txt", "top.txt/z"])
def test_a_path_beside_it_that_nothing_changed_is_still_no(
    layouts: Path, layout: str, path: str
) -> None:
    """Control: the directory holding the submodule is this repository's.

    Given `lib` and `lib/x`, `git ls-tree` lists everything in `lib`, the
    submodule included; it is not what `lib/x/y.txt` is inside.
    """
    code, stderr = _who(layouts / layout, path)

    assert code == ExitCode.NEGATIVE, stderr


def test_a_tree_git_cannot_read_cannot_run(layouts: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = GitReader._git

    def failing(self: GitReader, extra: Any = ()) -> Any:
        runner = real(self, extra)

        class _Runner:
            def __getattr__(self, name: str) -> Any:
                if name == "ls_tree":

                    def fail(*args: Any, **kwargs: Any) -> Any:
                        raise GitCommandError("ls-tree", 128)

                    return fail
                return getattr(runner, name)

        return _Runner()

    monkeypatch.setattr(GitReader, "_git", failing)

    code, stderr = _who(layouts / "bare.git", "lib/other.txt")

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "Git could not read the tree" in stderr
