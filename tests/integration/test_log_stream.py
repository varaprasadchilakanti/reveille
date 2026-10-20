# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The main `git log` is read in the background, split into records as it arrives."""

from __future__ import annotations

import io
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError

from reveille.adapters import git_reader
from reveille.adapters.git_reader import GitReader, _LogStream

pytestmark = pytest.mark.integration


class _Chunked(io.RawIOBase):
    """Gives its bytes back a few at a time, as a pipe can."""

    def __init__(self, data: bytes, size: int) -> None:
        self._data, self._size = data, size

    def readable(self) -> bool:
        return True

    def read(self, n: int = -1) -> bytes:
        taken, self._data = self._data[: self._size], self._data[self._size :]
        return taken


class _Done:
    """A finished process with the given output, in GitPython's handle's shape."""

    def __init__(self, stdout: Any, status: int = 0) -> None:
        self.args = ["git", "log"]
        self.proc = self
        self.stdout, self.stderr, self._status = stdout, io.BytesIO(b"oops"), status

    def poll(self) -> int:
        return self._status

    def wait(self) -> int:
        return self._status

    def kill(self) -> None:
        pass


def _output() -> bytes:
    big = "x" * 200_000  # one record longer than any read
    text = f"\x1ea\x1fJosé\x1e\x1eb\n{big}\x1ec\x1fé\x1e"
    return text.encode() + b"\xff tail"  # and a byte UTF-8 cannot decode


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1 << 16])
def test_records_are_split_as_the_whole_output_was(size: int) -> None:
    data = _output()
    stream = _LogStream(_Done(_Chunked(data, size)))

    assert stream.records() == data.decode("utf-8", "surrogateescape").split("\x1e")


def test_a_failing_git_is_a_git_error() -> None:
    stream = _LogStream(_Done(io.BytesIO(b"\x1epartial"), status=128))

    with pytest.raises(GitCommandError, match="oops"):
        stream.records()


def _python(code: str) -> Any:
    process = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    handle = type("Handle", (), {})()
    handle.args, handle.proc = ["python"], process
    return handle


def test_warnings_that_fill_the_error_pipe_do_not_stop_the_read() -> None:
    """Git writes warnings to stderr; unread, a full pipe would stop it for ever."""
    handle = _python(
        "import sys; sys.stderr.write('w' * 1_000_000); sys.stderr.flush();"
        "sys.stdout.write('\\x1erecord' * 100_000)"
    )
    stream = _LogStream(handle)
    result: list[list[str]] = []
    reader = threading.Thread(target=lambda: result.append(stream.records()), daemon=True)
    reader.start()
    reader.join(timeout=30)
    try:
        assert result, "the read stopped: stderr was not drained"
        assert len(result[0]) == 100_001
    finally:
        stream.close()


def test_close_stops_a_git_still_writing() -> None:
    handle = _python("import sys\nwhile True: sys.stdout.write('\\x1er' * 1000)")
    stream = _LogStream(handle)

    closer = threading.Thread(target=stream.close, daemon=True)
    closer.start()
    closer.join(timeout=20)
    stopped = handle.proc.poll() is not None
    handle.proc.kill()  # whatever happened, nothing is left writing

    assert stopped, "close() left Git running"


def test_a_failure_before_the_log_is_taken_stops_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The branch check runs while Git writes both logs; when it fails, neither is left running."""
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
    writers: list[Any] = []
    real = git_reader._LogStream

    def endless(process: Any, **kwargs: Any) -> _LogStream:
        # A log this small is written at once; stand in one that is not.
        process.proc.kill()
        writers.append(_python("import sys\nwhile True: sys.stdout.write('\\x1er' * 1000)"))
        return real(writers[-1], **kwargs)

    monkeypatch.setattr(git_reader, "_LogStream", endless)
    reader = GitReader(path)
    monkeypatch.setattr(reader, "_read_mailmap", lambda: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        reader.read_commits(None, None, None, [])
    stopped = len(writers) == 2 and all(w.proc.poll() is not None for w in writers)
    for writer in writers:
        writer.proc.kill()

    assert stopped, "Git was left running after the read failed"


def test_a_co_author_read_that_fails_credits_nobody_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=A",
            "-c",
            "user.email=a@e.test",
            "commit",
            "-qm",
            "a\n\nCo-authored-by: H <h@e.test>",
        ],
        cwd=path,
        check=True,
    )
    reader = GitReader(path)
    failing = _LogStream(_Done(io.BytesIO(b""), status=128))
    monkeypatch.setattr(
        reader, "_trailer_records", lambda _: reader.__class__._trailer_records(reader, failing)
    )

    commits = reader.read_commits(None, None, None, [])

    assert len(commits) == 1 and commits[0].co_authors == ()
    assert "co-author trailers could not be read" in caplog.text


class _FailsAfterOneRead(io.RawIOBase):
    """Gives one chunk of a pipe, then fails as a broken read would."""

    def __init__(self, pipe: Any, failure: BaseException) -> None:
        self._pipe, self._failure, self._reads = pipe, failure, 0

    def readable(self) -> bool:
        return True

    def read(self, n: int = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise self._failure
        return bytes(self._pipe.read(n))


@pytest.mark.parametrize("failure", [OSError("broken"), RuntimeError("unexpected")])
def test_a_read_that_fails_part_way_is_an_error_not_a_shorter_history(
    failure: BaseException,
) -> None:
    """Git can exit 0 although its output was not all read; that is not the whole log."""
    stream = _LogStream(_Done(_FailsAfterOneRead(io.BytesIO(b"\x1ea\x1eb" * 100_000), failure)))

    with pytest.raises(GitCommandError, match="could not be read"):
        stream.records()


def test_a_reader_that_fails_stops_git_rather_than_waiting_for_ever() -> None:
    """Unread, Git blocks on a full pipe, and the wait for it would never end."""
    handle = _python("import sys\nwhile True: sys.stdout.write('\\x1er' * 1000)")
    handle.proc.stdout = _FailsAfterOneRead(handle.proc.stdout, RuntimeError("unexpected"))
    stream = _LogStream(handle)
    raised: list[BaseException] = []

    def take() -> None:
        try:
            stream.raw_records()
        except GitCommandError as exc:
            raised.append(exc)

    reader = threading.Thread(target=take, daemon=True)
    reader.start()
    reader.join(timeout=20)
    stopped = handle.proc.poll() is not None
    handle.proc.kill()

    assert stopped, "Git was left writing to a pipe nobody reads"
    assert raised, "the failure was lost with the thread"


def test_the_main_log_is_stopped_when_the_second_cannot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    writers: list[Any] = []
    real = git_reader._LogStream

    def second_fails(process: Any, **kwargs: Any) -> _LogStream:
        process.proc.kill()
        if writers:
            raise RuntimeError("can't start new thread")
        writers.append(_python("import sys\nwhile True: sys.stdout.write('\\x1er' * 1000)"))
        return real(writers[-1], **kwargs)

    monkeypatch.setattr(git_reader, "_LogStream", second_fails)

    with pytest.raises(RuntimeError):
        GitReader(path).read_commits(None, None, None, [])
    stopped = writers[0].proc.poll() is not None
    writers[0].proc.kill()

    assert stopped, "the main log was left running"


def test_git_is_stopped_when_a_reader_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _python("import sys\nwhile True: sys.stdout.write('\\x1er' * 1000)")
    started: list[threading.Thread] = []
    real = threading.Thread.start

    def second_fails(thread: threading.Thread) -> None:
        if started:
            raise RuntimeError("can't start new thread")
        started.append(thread)
        real(thread)

    monkeypatch.setattr(threading.Thread, "start", second_fails)

    with pytest.raises(RuntimeError):
        _LogStream(handle)
    monkeypatch.undo()
    handle.proc.wait(timeout=20)  # killed, so it ends; left running, this times out
    started[0].join(timeout=20)


def test_git_writes_its_log_in_blocks(tmp_path: Path) -> None:
    """To a pipe, Git flushes after every commit unless told not to: on a 100,000-commit
    history, 100,000 writes against 1,001, and about 0.6 s of system time."""
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)

    assert GitReader(path)._repo.git.environment().get("GIT_FLUSH") == "0"


def test_one_string_per_hash_is_shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Four copies of each hash were 30 MB on 100,000 commits: one is kept."""
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for n in range(3):
        (path / "a.txt").write_text(str(n), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        subprocess.run(
            ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", f"c{n}"],
            cwd=path,
            check=True,
        )
    order: list[str] = []
    real = git_reader._shared_trailer_records

    def keep(records: Any, canonical: Any) -> Any:
        order.extend(canonical)
        shared = real(records, canonical)
        kept = [r for r in shared if r.strip()]
        assert all(r is canonical[r] for r in kept), "a trailer-less record kept its own copy"
        return shared

    monkeypatch.setattr(git_reader, "_shared_trailer_records", keep)
    commits = GitReader(path).read_commits(None, None, None, [])

    by_value = {sha: sha for sha in order}
    assert len(commits) == 3
    assert all(c.sha is by_value[c.sha] for c in commits), "a commit holds its own copy"


def test_a_trailer_record_for_an_unlisted_hash_is_kept_whole() -> None:
    """So it still fails the check that the records line up with `rev-list`."""
    sha, forged = "a" * 40, "b" * 40
    records = [f"{sha}\x1f\n", f"{forged}\x1f\n", f"{sha}\x1fCo-authored-by: X <x@e.test>"]

    shared = git_reader._shared_trailer_records(records, {sha: sha})

    assert isinstance(shared, list)
    assert shared[0] == sha and shared[1] == f"{forged}\x1f\n" and shared[2].endswith("x@e.test>")
