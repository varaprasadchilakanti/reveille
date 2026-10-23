# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A linked worktree made inside a bare repository's directory takes reports and `init`.

`git -C bare.git worktree add wt` puts the checkout in `bare.git/wt`. Every
directory above it looked like Git's, so the default output and `init` were
refused there. The walk up now stops at a worktree root whose `.git` file is
named back by its Git directory; a `.git` file that is not stays refused.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.replacing import write_replacing

pytestmark = pytest.mark.integration


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture(params=[[], ["--relative-paths"]], ids=["absolute", "relative"])
def bare(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    source = tmp_path / "src"
    _git("init", "-q", "-b", "main", str(source))
    (source / "a.txt").write_text("a", encoding="utf-8")
    _git("add", "a.txt", cwd=source)
    _git("commit", "-qm", "a", cwd=source)
    path = tmp_path / "b.git"
    _git("clone", "-q", "--bare", str(source), str(path))
    _git("worktree", "add", "-q", *request.param, "wt", "main", cwd=path)
    return path


def _invoke(cwd: Path, *args: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    monkeypatch.chdir(cwd)
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, " ".join(result.stderr.split())


def test_the_default_output_is_written_in_the_worktree(
    bare: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, stderr = _invoke(bare / "wt", "generate", "-q", monkeypatch=monkeypatch)

    assert code == ExitCode.SUCCESS, stderr
    assert (bare / "wt" / "reveille-report.html").is_file()


def test_init_writes_in_the_worktree(bare: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, stderr = _invoke(bare / "wt", "init", monkeypatch=monkeypatch)

    assert code == ExitCode.SUCCESS, stderr
    assert (bare / "wt" / "reveille.toml").is_file()


@pytest.mark.parametrize("inside", ["refs/x.html", "worktrees/wt/x.html", "x.html"])
def test_git_s_own_files_around_it_are_still_refused(
    bare: Path, monkeypatch: pytest.MonkeyPatch, inside: str
) -> None:
    out = bare / inside
    code, stderr = _invoke(bare / "wt", "generate", "-q", "-o", str(out), monkeypatch=monkeypatch)

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "inside a Git directory" in stderr
    assert not out.exists()


def test_a_git_file_its_git_directory_does_not_name_is_refused(
    bare: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointing at the real worktree's Git directory is not enough: it names wt/.git."""
    planted = bare / "refs" / "heads"
    (planted / ".git").write_text(f"gitdir: {bare / 'worktrees' / 'wt'}\n", encoding="utf-8")
    out = planted / "x.html"

    code, stderr = _invoke(bare / "wt", "generate", "-q", "-o", str(out), monkeypatch=monkeypatch)

    assert code == ExitCode.CANNOT_RUN, stderr
    with pytest.raises(OSError, match="inside a Git directory"):
        write_replacing(out, "x", encoding="utf-8")
    assert not out.exists()


def test_the_writer_takes_the_worktree_and_refuses_beside_it(bare: Path) -> None:
    write_replacing(bare / "wt" / "r.html", "x", encoding="utf-8")

    assert (bare / "wt" / "r.html").read_text(encoding="utf-8") == "x"
    with pytest.raises(OSError, match="inside a Git directory"):
        write_replacing(bare / "refs" / "r.html", "x", encoding="utf-8")
