# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The history read logs the listed commits in chunks, and gives what one `git log` gives."""

from __future__ import annotations

import datetime
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError
from typer.testing import CliRunner

from reveille.adapters import git_reader
from reveille.adapters.git_reader import GitReader, _build_log_args, _LogStream
from reveille.cli import app
from reveille.exceptions import RepositoryError

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str, name: str = "Ana", when: int = 1_700_000_000) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
        "GIT_AUTHOR_DATE": f"@{when} +0000",
        "GIT_COMMITTER_DATE": f"@{when} +0000",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    ).stdout


def _commit(repo: Path, message: str, when: int, name: str = "Ana") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message, name=name, when=when)


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A root commit, a rename, a binary file, non-ASCII and spaced paths, a deletion, a merge."""
    repo = tmp_path_factory.mktemp("chunked") / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    day = 86_400
    when = 1_700_000_000
    (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    _commit(repo, "root", when)
    (repo / "src").mkdir()
    (repo / "src" / "m.py").write_text("x = 1\n" * 40, encoding="utf-8")
    _commit(repo, "module", when + day)
    _git(repo, "mv", "src/m.py", "src/n.py")
    _commit(repo, "rename", when + 2 * day)
    (repo / "logo.bin").write_bytes(bytes(range(256)) * 4)
    _commit(repo, "binary", when + 3 * day)
    (repo / "é dir").mkdir()
    (repo / "é dir" / "ü file.txt").write_text("u\n", encoding="utf-8")
    _commit(repo, "non-ascii", when + 4 * day, name="José")
    (repo / "a.txt").unlink()
    _commit(repo, "delete", when + 5 * day)
    # A separator in an author name splits its record; it must split the same way.
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _commit(repo, "separator", when + 6 * day, name="Eve\x1eforged")
    _git(repo, "switch", "-qc", "side")
    (repo / "side.txt").write_text("s\n", encoding="utf-8")
    _commit(repo, "side", when + 7 * day)
    _git(repo, "switch", "-q", "main")
    # Inside and outside `src` at once: a path selection must list only its part.
    (repo / "src" / "n.py").write_text("x = 2\n" * 41, encoding="utf-8")
    (repo / "b.txt").write_text("b\nc\n", encoding="utf-8")
    _commit(repo, "edit", when + 8 * day)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "side", when=when + 9 * day)
    for i in range(6):
        (repo / "src" / f"f{i}.py").write_text(f"v = {i}\n", encoding="utf-8")
        _commit(repo, f"file {i}", when + (10 + i) * day)
    # Dated before its parent, as a rebase or a wrong clock leaves it: a chunk
    # Git sorted by date would come back in another order.
    (repo / "late.txt").write_text("l\n", encoding="utf-8")
    _commit(repo, "dated early", when - 30 * day)
    (repo / "later.txt").write_text("l\n", encoding="utf-8")
    _commit(repo, "dated late", when + 40 * day)
    return repo


@pytest.fixture()
def one_commit_chunks(monkeypatch: pytest.MonkeyPatch) -> list[_LogStream]:
    """Make chunks of two commits, three processes at once; record each chunk started."""
    monkeypatch.setattr(git_reader, "_MIN_HISTORY_CHUNK", 2)
    monkeypatch.setattr(git_reader, "_CHUNKS_PER_WORKER", 1_000)
    monkeypatch.setattr(git_reader, "_history_workers", lambda: 3)
    started: list[_LogStream] = []
    real = git_reader._LogStream

    def counting(process: Any, **kwargs: Any) -> _LogStream:
        stream = real(process, **kwargs)
        if "--stdin" in process.args:
            started.append(stream)
        return stream

    monkeypatch.setattr(git_reader, "_LogStream", counting)
    return started


_SELECTIONS = {
    "whole history": {},
    "one path": {"path": "src"},
    "excluded path": {"exclude_paths": ["src"]},
    "name-status": {"name_status": True},
    "window": {
        "since": datetime.date(2023, 11, 17),
        "until": datetime.date(2023, 11, 25),
    },
    "no line counts": {"line_counts": False},
}


@pytest.mark.parametrize("selection", list(_SELECTIONS.values()), ids=list(_SELECTIONS))
def test_chunks_give_the_bytes_one_git_log_gives(
    history: Path, one_commit_chunks: list[_LogStream], selection: dict[str, Any]
) -> None:
    reader = GitReader(history)
    log_args, rev_list_args, listed_args = _build_log_args(
        "refs/heads/main",
        selection.get("since"),
        selection.get("until"),
        line_counts=selection.get("line_counts", True),
        path=selection.get("path"),
        name_status=selection.get("name_status", False),
        exclude_paths=selection.get("exclude_paths", ()),
    )
    one = _LogStream(reader._git().log(*log_args, as_process=True))
    try:
        expected = one.raw_records()
    finally:
        one.close()

    shas = reader._listed_commits("refs/heads/main", rev_list_args)
    chunked = reader._history_stream(listed_args, shas)
    try:
        records = chunked.raw_records()
    finally:
        chunked.close()

    line_counts = selection.get("line_counts", True) and not selection.get("name_status", False)
    assert len(one_commit_chunks) == (-(-len(shas) // 2) if line_counts else 1)
    assert len(shas) > 1
    assert records == expected


@pytest.mark.parametrize("selection", list(_SELECTIONS.values()), ids=list(_SELECTIONS))
def test_a_chunked_read_counts_what_a_single_one_counts(
    history: Path, monkeypatch: pytest.MonkeyPatch, selection: dict[str, Any]
) -> None:
    def read() -> tuple[Any, ...]:
        reader = GitReader(history)
        commits = reader.read_commits(
            None,
            selection.get("since"),
            selection.get("until"),
            [],
            area_depth=1,
            line_counts=selection.get("line_counts", True),
            path=selection.get("path"),
            name_status=selection.get("name_status", False),
            exclude_paths=selection.get("exclude_paths", ()),
        )
        return (
            commits,
            reader._file_stats,
            reader.area_activity,
            reader.files_added,
            reader.commits_unreadable,
            reader.merges_excluded,
        )

    single = read()  # fewer commits than the smallest chunk: one process
    monkeypatch.setattr(git_reader, "_MIN_HISTORY_CHUNK", 1)
    monkeypatch.setattr(git_reader, "_CHUNKS_PER_WORKER", 1_000)
    monkeypatch.setattr(git_reader, "_history_workers", lambda: 3)

    assert read() == single


def test_a_chunk_that_fails_fails_the_read_and_leaves_no_git_running(
    history: Path, one_commit_chunks: list[_LogStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = GitReader(history)
    real = reader._listed_commits

    def with_a_missing_object(rev: str, rev_list_args: list[str]) -> list[str]:
        shas = real(rev, rev_list_args)
        return [*shas[:2], "0" * 40, *shas[2:]]

    monkeypatch.setattr(reader, "_listed_commits", with_a_missing_object)

    with pytest.raises(RepositoryError, match="could not read the commits"):
        reader.read_commits(None, None, None, [])
    assert one_commit_chunks
    assert all(s._process.proc.poll() is not None for s in one_commit_chunks)


def test_one_cpu_reads_every_commit_in_one_process(
    history: Path, one_commit_chunks: list[_LogStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_reader, "_history_workers", lambda: 1)

    GitReader(history).read_commits(None, None, None, [])

    assert len(one_commit_chunks) == 1


def test_a_chunk_whose_git_is_killed_fails_the_command_with_exit_2(
    history: Path, one_commit_chunks: list[_LogStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    started = 0
    real = git_reader._LogStream

    def second_killed(process: Any, **kwargs: Any) -> _LogStream:
        nonlocal started
        if "--stdin" in process.args:
            started += 1
            if started == 2:
                # A Git that is still writing when it is killed, as by the OOM killer.
                process.proc.kill()
                process = _python("import sys, time\nsys.stdout.write('\\x1e')\ntime.sleep(60)")
                process.proc.kill()
        return real(process, **kwargs)

    monkeypatch.setattr(git_reader, "_LogStream", second_killed)

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(history), "--format", "json", "-o", "-"]
    )

    assert started >= 2
    assert result.exit_code == 2, result.output
    assert result.stdout == ""


def _python(code: str) -> Any:
    process = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    handle = type("Handle", (), {})()
    handle.args, handle.proc = ["python"], process
    return handle


def test_no_more_than_the_workers_run_at_once() -> None:
    running = peak = 0

    class _Open(_Finished):
        def __init__(self) -> None:
            nonlocal running, peak
            super().__init__(b"\x1ex")
            running += 1
            peak = max(peak, running)

        def close(self) -> None:
            nonlocal running
            running -= 1

    log = git_reader._ChunkedLog(lambda chunk: _Open(), [[str(i)] for i in range(10)], 3)  # type: ignore[arg-type,return-value]
    records = log.raw_records()

    assert peak == 3
    assert len(records) == 11


def test_a_cpu_quota_caps_the_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "cgroup"
    (root / "a" / "b").mkdir(parents=True)
    membership = tmp_path / "self-cgroup"
    membership.write_text("0::/a/b\n", encoding="utf-8")
    (root / "cpu.max").write_text("max 100000\n", encoding="ascii")
    # Above the hierarchy's root: not a cgroup, never read.
    (tmp_path / "cpu.max").write_text("100000 100000\n", encoding="ascii")
    (root / "a" / "cpu.max").write_text("250000 100000\n", encoding="ascii")  # 2.5 CPUs
    (root / "a" / "b" / "cpu.max").write_text("150000 100000\n", encoding="ascii")  # 1.5

    assert git_reader._cgroup_cpu_quota(membership, root) == 2  # the smallest, rounded up
    (root / "a" / "b" / "cpu.max").write_text("max 100000\n", encoding="ascii")
    assert git_reader._cgroup_cpu_quota(membership, root) == 3  # an ancestor's
    (root / "a" / "cpu.max").unlink()
    assert git_reader._cgroup_cpu_quota(membership, root) is None
    assert git_reader._cgroup_cpu_quota(tmp_path / "absent", root) is None

    monkeypatch.setattr(os, "process_cpu_count", lambda: 20, raising=False)
    monkeypatch.setattr(git_reader, "_cgroup_cpu_quota", lambda: 2)
    assert git_reader._history_workers() == 2


def test_a_quota_at_the_cgroup_root_counts(tmp_path: Path) -> None:
    """A container with its own cgroup namespace sees its quota at the root."""
    membership = tmp_path / "self-cgroup"
    membership.write_text("0::/\n", encoding="utf-8")
    (tmp_path / "cpu.max").write_text("200000 100000\n", encoding="ascii")

    assert git_reader._cgroup_cpu_quota(membership, tmp_path) == 2


def test_no_cgroup_v2_line_means_no_quota(tmp_path: Path) -> None:
    membership = tmp_path / "self-cgroup"
    membership.write_text("4:cpu,cpuacct:/docker/x\n", encoding="utf-8")
    (tmp_path / "cpu.max").write_text("100000 100000\n", encoding="ascii")

    assert git_reader._cgroup_cpu_quota(membership, tmp_path) is None


def test_without_an_affinity_call_the_machines_cpus_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "process_cpu_count", raising=False)
    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 3)
    monkeypatch.setattr(git_reader, "_cgroup_cpu_quota", lambda: None)

    assert git_reader._history_workers() == 3


def test_feeding_a_git_that_has_exited_does_not_raise() -> None:
    """Its exit status fails the read; the broken pipe is not the error reported."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.wait()
    handle = type("Handle", (), {})()
    handle.args, handle.proc = ["git", "log"], process
    stream = _LogStream(handle)

    stream.feed(b"0" * 41 * 100_000)

    with pytest.raises(GitCommandError):
        stream.raw_records()
    stream.close()


def test_a_chunk_that_cannot_be_started_stops_those_already_running(
    history: Path, one_commit_chunks: list[_LogStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    fed = 0
    real = _LogStream.feed

    def second_fails(self: _LogStream, data: bytes) -> None:
        nonlocal fed
        fed += 1
        if fed == 2:
            raise OSError("no more processes")
        real(self, data)

    monkeypatch.setattr(_LogStream, "feed", second_fails)

    with pytest.raises(OSError, match="no more processes"):
        GitReader(history).read_commits(None, None, None, [])
    assert len(one_commit_chunks) == 2
    assert all(s._process.proc.poll() is not None for s in one_commit_chunks)


def test_the_pipe_constant_is_subprocess_pipe() -> None:
    assert git_reader._PIPE == subprocess.PIPE


@pytest.mark.parametrize(("cpus", "workers"), [(0, 1), (1, 1), (4, 4), (64, 8)])
def test_the_workers_follow_the_cpus_allowed_up_to_eight(
    monkeypatch: pytest.MonkeyPatch, cpus: int, workers: int
) -> None:
    monkeypatch.setattr(os, "process_cpu_count", lambda: cpus, raising=False)
    monkeypatch.setattr(git_reader, "_cgroup_cpu_quota", lambda: None)

    assert git_reader._history_workers() == workers


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in program is a shell script")
def test_a_chunked_read_runs_no_diff_program_the_repository_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    marker = tmp_path / "ran"
    program = tmp_path / "program"
    program.write_text(f"#!/bin/sh\necho x >> '{marker.as_posix()}'\ncat \"$1\"\n", "utf-8")
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".gitattributes").write_text("*.txt diff=x\n", encoding="utf-8")
    for i in range(3):
        (repo / "a.txt").write_text(f"{i}\n", encoding="utf-8")
        _commit(repo, f"c{i}", 1_700_000_000 + i)
    _git(repo, "config", "diff.x.textconv", program.as_posix())
    _git(repo, "config", "diff.external", program.as_posix())
    # Guard the guard: plain Git does run them.
    subprocess.run(["git", "log", "-p"], cwd=repo, capture_output=True, check=True)
    assert marker.exists(), "the fixture does not make git log run the program"
    marker.unlink()
    monkeypatch.setattr(git_reader, "_MIN_HISTORY_CHUNK", 1)
    monkeypatch.setattr(git_reader, "_history_workers", lambda: 2)

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "-o", "-"])

    assert result.exit_code == 0, result.stderr
    assert not marker.exists(), "a program named in the repository's config ran"


class _Finished:
    """A chunk's `git log` that has already written `output`."""

    def __init__(self, output: bytes) -> None:
        self._records = output.split(b"\x1e")

    def wait_read(self) -> None:
        pass

    def raw_records(self) -> list[bytes]:
        return self._records

    def close(self) -> None:
        pass


def test_chunk_outputs_are_joined_as_one_output_would_split() -> None:
    outputs = [b"lead\x1ea\x1eb-", b"tail\x1ec", b"\x1ed"]
    chunks = [[str(i)] for i in range(len(outputs))]

    log = git_reader._ChunkedLog(lambda chunk: _Finished(outputs[int(chunk[0])]), chunks, 2)  # type: ignore[arg-type,return-value]

    assert log.raw_records() == b"".join(outputs).split(b"\x1e")
