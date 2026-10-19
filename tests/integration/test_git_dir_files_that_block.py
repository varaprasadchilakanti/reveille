# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A file Git reads before anything else, if it would block, stops Reveille, not hangs it.

A named pipe at `.git/config`, `packed-refs`, `shallow` and the rest makes Git
and GitPython wait for ever; `include.path` can name a pipe, `/dev/stdin` or
`/dev/zero`, which GitPython's config reader reads without end. A copied
directory or an archive can carry one; `git clone` cannot. Each is refused
before Git runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from reveille.adapters.git_reader import _include_paths

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX"),
]

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


def _summary(
    repo: Path, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Run `summary` in a child, with no terminal to read; None if it had to be killed."""
    try:
        return subprocess.run(
            [sys.executable, "-c", _CHILD, "summary", "--repo", str(repo)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            env=None if env is None else {**os.environ, **env},
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None


def _refused(
    repo: Path, because: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    done = _summary(repo, cwd, env)
    assert done is not None, "Reveille waited on it"
    assert done.returncode == 2, done.stderr
    assert because in done.stderr and "not a regular file" in done.stderr, done.stderr


def test_plain_git_waits_on_a_pipe_for_its_config(repo: Path) -> None:
    """Positive control: the hang is Git's, and real."""
    (repo / ".git" / "config").unlink()
    os.mkfifo(repo / ".git" / "config")
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(["git", "status"], cwd=repo, capture_output=True, timeout=5, check=False)


@pytest.mark.parametrize(
    "name",
    [
        "config",
        "HEAD",
        "packed-refs",
        "shallow",
        "commondir",
        "config.worktree",
        "objects/info/alternates",
    ],
)
def test_a_pipe_git_reads_first_is_refused(repo: Path, name: str) -> None:
    target = repo / ".git" / name
    if target.exists():
        target.unlink()
    os.mkfifo(target)

    _refused(repo, name)


@pytest.mark.parametrize("named", ["extra.cfg", "/dev/zero"])
def test_an_include_that_blocks_or_never_ends_is_refused(repo: Path, named: str) -> None:
    if named == "extra.cfg":
        os.mkfifo(repo / ".git" / "extra.cfg")  # relative to the including file
    subprocess.run(["git", "config", "include.path", named], cwd=repo, check=True)

    _refused(repo, named)


@pytest.mark.parametrize("where", ["inside the repository", "GIT_DIR names it"])
def test_an_include_is_refused_wherever_reveille_is_run_from(repo: Path, where: str) -> None:
    """Git started inside the repository read its config, and the pipe, before the check."""
    os.mkfifo(repo / ".git" / "extra.cfg")
    subprocess.run(["git", "config", "include.path", "extra.cfg"], cwd=repo, check=True)

    if where == "inside the repository":
        _refused(repo, "extra.cfg", cwd=repo)
    else:
        _refused(repo, "extra.cfg", env={"GIT_DIR": str(repo / ".git")})


def test_a_conditional_include_is_checked_whatever_its_condition(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "includeIf.gitdir:/nowhere/.path", "/dev/stdin"], cwd=repo, check=True
    )

    _refused(repo, "/dev/stdin")


def test_an_included_file_too_large_to_be_a_configuration_is_refused(repo: Path) -> None:
    with (repo / ".git" / "huge.cfg").open("wb") as handle:
        handle.truncate(9 * 1024 * 1024)
    subprocess.run(["git", "config", "include.path", "huge.cfg"], cwd=repo, check=True)

    done = _summary(repo)

    assert done is not None and done.returncode == 2, done
    assert "larger than any configuration" in done.stderr


def test_packed_refs_past_the_configuration_limit_are_read(repo: Path) -> None:
    """`packed-refs` grows with the refs, so only a pipe or a device there is refused."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    lines = [f"{head} refs/tags/t{index:07d}\n" for index in range(160_000)]
    packed = repo / ".git" / "packed-refs"
    packed.write_text("# pack-refs with: peeled sorted\n" + "".join(lines), encoding="utf-8")
    assert packed.stat().st_size > 8 * 1024 * 1024, "positive control: past the limit"

    done = _summary(repo)

    assert done is not None and done.returncode == 0, done


def test_a_regular_include_and_a_linked_worktree_are_read(repo: Path, tmp_path: Path) -> None:
    (repo / ".git" / "extra.cfg").write_text("[core]\n\tabbrev = 12\n", encoding="utf-8")
    subprocess.run(["git", "config", "include.path", "extra.cfg"], cwd=repo, check=True)
    subprocess.run(
        ["git", "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "side"], cwd=repo, check=True
    )

    for where in (repo, tmp_path / "wt"):
        done = _summary(where)
        assert done is not None and done.returncode == 0, done


@pytest.mark.parametrize(
    "written",
    [
        "[include]\n\tpath = pi\\\npe\n",  # a line continuation
        "\ufeff[include]\n\tpath = pipe\n",  # a byte-order mark before the section
        '[core]\n\tx = "a\\\n[core]"\n[include]\n\tpath = pipe\n',  # a section in a value
    ],
    ids=["continuation", "byte-order-mark", "section-in-a-value"],
)
def test_an_include_is_found_however_git_reads_it(repo: Path, written: str) -> None:
    """Git's grammar, not a pattern, says which keys are includes."""
    os.mkfifo(repo / ".git" / "pipe")
    config = repo / ".git" / "config"
    before = config.read_text(encoding="utf-8")
    # Git skips a byte-order mark only at the start of the file.
    bom = written.startswith("\ufeff")
    config.write_text(written + before if bom else before + written, encoding="utf-8")

    _refused(repo, "pipe")


def test_an_include_under_gits_install_prefix_is_refused(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "include.path", "%(prefix)/../dev/stdin"], cwd=repo, check=True
    )

    done = _summary(repo)

    assert done is not None and done.returncode == 2, done
    assert "install prefix" in done.stderr


@pytest.mark.unit
class TestIncludePaths:
    def test_every_include_section_form_is_read(self, tmp_path: Path) -> None:
        text = (
            "[core]\n\tpath = not-an-include\n"
            "[include]\n\tpath = a.cfg  # a comment\n"
            '[includeIf "gitdir:~/work/"]\n\tPATH = "~/b c.cfg"\n'
            "[Include] path = d.cfg\n"
            "[user]\n\tpath = nor-this\n"
            "[include]\n\tpath = e\\\\f ; another\n"
        )

        (tmp_path / "c.cfg").write_text(text, encoding="utf-8")

        assert _include_paths(tmp_path / "c.cfg") == ["a.cfg", "~/b c.cfg", "d.cfg", "e\\f"]

    def test_a_file_with_no_include_lists_none(self, tmp_path: Path) -> None:
        (tmp_path / "c.cfg").write_text("[core]\n\tbare = false\n", encoding="utf-8")

        assert _include_paths(tmp_path / "c.cfg") == []
