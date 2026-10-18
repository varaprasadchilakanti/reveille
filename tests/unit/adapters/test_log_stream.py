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

pytestmark = pytest.mark.unit


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
