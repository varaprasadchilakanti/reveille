# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The branches taken where the platform lacks POSIX descriptors, run on any platform.

Windows has no `O_NOFOLLOW` and no `dir_fd`, and before Python 3.13 cannot set a
mode through a descriptor. Each test takes those away and checks the promise
still holds, so the Windows branches run on every CI leg, not only on Windows.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import reveille.replacing as replacing
from reveille.nofollow import open_not_following
from reveille.replacing import write_replacing


@pytest.fixture
def no_descriptors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take `write_replacing` down its Windows branch, where `chmod` takes no descriptor."""
    monkeypatch.setattr(replacing, "_DIRECTORY_DESCRIPTORS", False)
    real_chmod = os.chmod

    def chmod(path: object, mode: int, **kwargs: object) -> None:
        if isinstance(path, int):
            raise TypeError("chmod: path should be string, bytes or os.PathLike, not int")
        real_chmod(path, mode, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "chmod", chmod)
    monkeypatch.setattr(os, "supports_fd", os.supports_fd - {os.chmod})


def _git_directory(path: Path) -> Path:
    (path / "objects").mkdir(parents=True)
    (path / "refs" / "heads").mkdir(parents=True)
    (path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return path


@pytest.mark.usefixtures("no_descriptors")
def test_an_existing_file_is_replaced(tmp_path: Path) -> None:
    """Writing over a report from an earlier run is the common case, not an edge."""
    target = tmp_path / "report.html"
    target.write_text("old", encoding="utf-8")

    write_replacing(target, "new", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["report.html"]


@pytest.mark.usefixtures("no_descriptors")
@pytest.mark.parametrize("inside", ["", "refs/heads"])
def test_a_git_directory_or_one_inside_it_is_refused(tmp_path: Path, inside: str) -> None:
    git_dir = _git_directory(tmp_path / "repo.git")
    target = git_dir / inside / "report.html"

    with pytest.raises(OSError, match="inside a Git directory") as caught:
        write_replacing(target, "x", encoding="utf-8")

    assert caught.value.errno == errno.EPERM
    assert not target.exists()


@pytest.mark.usefixtures("no_descriptors")
def test_a_linked_worktree_inside_a_git_directory_is_written(tmp_path: Path) -> None:
    git_dir = _git_directory(tmp_path / "repo.git")
    worktree = git_dir / "wt"
    worktree.mkdir()
    admin = git_dir / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    (admin / "gitdir").write_text(f"{worktree / '.git'}\n", encoding="utf-8")

    write_replacing(worktree / "report.html", "x", encoding="utf-8")

    assert (worktree / "report.html").read_text(encoding="utf-8") == "x"


@pytest.fixture
def no_nofollow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take `open_not_following` down its Windows branch: no `O_NOFOLLOW` flag."""
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="links")
@pytest.mark.usefixtures("no_nofollow")
def test_a_link_is_refused_without_the_flag(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.write_text("secret", encoding="utf-8")
    link = tmp_path / ".mailmap"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("this account cannot make links")

    with pytest.raises(OSError) as caught:
        open_not_following(link)

    assert caught.value.errno == errno.ELOOP


@pytest.mark.usefixtures("no_nofollow")
def test_a_regular_file_opens_without_the_flag(tmp_path: Path) -> None:
    plain = tmp_path / ".mailmap"
    plain.write_text("A <a@example.com>\n", encoding="utf-8")

    descriptor = open_not_following(plain)
    try:
        assert os.read(descriptor, 64) == b"A <a@example.com>\n"
    finally:
        os.close(descriptor)


def test_a_git_file_naming_a_path_that_is_not_utf8_names_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows decodes file names strictly: no directory there can have that name."""
    from reveille.adapters import git_reader

    monkeypatch.setattr(os, "fsdecode", lambda raw: raw.decode("utf-8"))
    tree = tmp_path / "wt"
    tree.mkdir()
    (tree / ".git").write_bytes(b"gitdir: /x\xff\n")

    assert git_reader.main_worktree_of(tree) is None
