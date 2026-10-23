# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`write_replacing` replaces only a regular file; a pipe or a device stays what it was.

Moving a new file over a name replaces whatever the name held: run as root,
`-o /dev/null` would have put a regular file where the device was.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from reveille.replacing import write_replacing


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_a_pipe_is_refused_and_left_in_place(tmp_path: Path) -> None:
    pipe = tmp_path / "out.html"
    os.mkfifo(pipe)

    with pytest.raises(OSError, match="not a regular file"):
        write_replacing(pipe, "x", encoding="utf-8")

    assert stat.S_ISFIFO(pipe.stat().st_mode)
    assert [p.name for p in tmp_path.iterdir()] == ["out.html"], "no temporary file left"


def test_a_regular_file_is_replaced(tmp_path: Path) -> None:
    target = tmp_path / "out.html"
    target.write_text("old", encoding="utf-8")

    write_replacing(target, "new", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "new"


def _git_directory(path: Path) -> Path:
    """A directory Git would take as a Git directory: `HEAD`, `objects` and `refs`."""
    (path / "objects").mkdir(parents=True)
    (path / "refs" / "heads").mkdir(parents=True)
    (path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return path


def _files(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX directory descriptors")
def test_a_directory_swapped_for_a_link_after_the_check_is_not_written_through(
    tmp_path: Path,
) -> None:
    store = _git_directory(tmp_path / "other.git")
    before = _files(store)
    out = tmp_path / "out"
    out.mkdir()
    target = out / "r.html"  # checked here, then the directory is swapped
    out.rmdir()
    out.symlink_to(store / "refs" / "heads")

    with pytest.raises(OSError):
        write_replacing(target, "<html>", encoding="utf-8")

    assert _files(store) == before


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX directory descriptors")
def test_a_directory_above_swapped_for_a_git_directory_is_found_from_inside(
    tmp_path: Path,
) -> None:
    """The last name is a real directory; a link further up leads into a Git directory."""
    store = _git_directory(tmp_path / "other.git")
    before = _files(store)
    (tmp_path / "a").symlink_to(store)
    target = tmp_path / "a" / "refs" / "r.html"

    with pytest.raises(OSError, match="inside a Git directory"):
        write_replacing(target, "<html>", encoding="utf-8")

    assert _files(store) == before


@pytest.mark.parametrize("where", ["", "refs/heads"])
@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX directory descriptors")
def test_a_git_directory_or_one_inside_it_is_refused(tmp_path: Path, where: str) -> None:
    store = _git_directory(tmp_path / "other.git")
    before = _files(store)

    with pytest.raises(OSError, match="inside a Git directory"):
        write_replacing(store / where / "r.html", "<html>", encoding="utf-8")

    assert _files(store) == before


def test_a_directory_with_only_some_of_the_names_is_written(tmp_path: Path) -> None:
    (tmp_path / "refs").mkdir()
    (tmp_path / "HEAD").write_text("notes", encoding="utf-8")

    write_replacing(tmp_path / "refs" / "r.html", "<html>", encoding="utf-8")

    assert (tmp_path / "refs" / "r.html").read_text(encoding="utf-8") == "<html>"
    assert sorted(p.name for p in (tmp_path / "refs").iterdir()) == ["r.html"]


def test_a_kept_mode_is_set_and_no_temporary_is_left(tmp_path: Path) -> None:
    target = tmp_path / "out.html"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)

    write_replacing(target, "new", encoding="utf-8")

    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert [p.name for p in tmp_path.iterdir()] == ["out.html"]


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX directory descriptors")
def test_a_directory_swapped_for_a_link_anywhere_is_not_written_through(tmp_path: Path) -> None:
    """Not only into a Git directory: the place checked is the only place written."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "out"
    out.symlink_to(elsewhere)

    with pytest.raises(OSError):
        write_replacing(out / "r.html", "<html>", encoding="utf-8")

    assert list(elsewhere.iterdir()) == []


def test_a_failed_move_removes_the_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", refuse)

    with pytest.raises(OSError, match="No space"):
        write_replacing(tmp_path / "out.html", "<html>", encoding="utf-8")

    assert list(tmp_path.iterdir()) == []


def test_a_head_that_is_a_directory_is_no_git_directory(tmp_path: Path) -> None:
    (tmp_path / "HEAD").mkdir()
    (tmp_path / "objects").mkdir()
    (tmp_path / "refs").mkdir()

    write_replacing(tmp_path / "refs" / "r.html", "<html>", encoding="utf-8")

    assert (tmp_path / "refs" / "r.html").is_file()


_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.mark.skipif(_AS_ROOT or not hasattr(os, "O_PATH"), reason="root reads any directory")
@pytest.mark.parametrize("unreadable", ["out", "."], ids=["its directory", "one above"])
def test_a_directory_that_cannot_be_listed_is_still_written_into(
    tmp_path: Path, unreadable: str
) -> None:
    """Making a file needs write and search permission; listing the directory is not needed."""
    out = tmp_path / "out"
    out.mkdir()
    locked = tmp_path / unreadable
    locked.chmod(0o300)
    try:
        write_replacing(out / "r.html", "x", encoding="utf-8")
    finally:
        locked.chmod(0o700)

    assert (out / "r.html").read_text(encoding="utf-8") == "x"


@pytest.mark.skipif(_AS_ROOT or not hasattr(os, "O_PATH"), reason="root reads any directory")
def test_a_git_directory_that_cannot_be_listed_is_still_refused(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    for name in ("objects", "refs"):
        (git / name).mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    git.chmod(0o300)
    try:
        with pytest.raises(OSError, match="inside a Git directory"):
            write_replacing(git / "objects" / "r.html", "x", encoding="utf-8")
    finally:
        git.chmod(0o700)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="links")
def test_a_git_directory_whose_head_link_dangles_is_refused(tmp_path: Path) -> None:
    """Git reads a `HEAD` linked to a branch only `packed-refs` holds."""
    git = tmp_path / "bare.git"
    for name in ("objects", "refs"):
        (git / name).mkdir(parents=True)
    (git / "HEAD").symlink_to("refs/heads/main")

    with pytest.raises(OSError, match="inside a Git directory"):
        write_replacing(git / "objects" / "r.html", "x", encoding="utf-8")
