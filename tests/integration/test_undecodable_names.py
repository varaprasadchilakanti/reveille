# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""An author or branch name that is not UTF-8 is shown with U+FFFD, in every format.

Git stores both as bytes. Decoded, a byte that is not UTF-8 became a lone
surrogate, and the HTML and CSV writers stopped on it with "This is a defect in
Reveille"; GitPython, reading HEAD, stopped on such a branch before the history.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("undecodable") / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    tree = subprocess.run(
        ["git", "write-tree"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    raw = (
        f"tree {tree}\n".encode()
        + b"author Bad\xff\xfe Name <b\xffad@e.test> 1700000000 +0000\n"
        + b"committer C <c@e.test> 1700000000 +0000\n\nm\n"
    )
    sha = (
        subprocess.run(
            ["git", "hash-object", "-t", "commit", "-w", "--stdin", "--literally"],
            cwd=path,
            check=True,
            input=raw,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )
    subprocess.run(["git", "update-ref", "refs/heads/main", sha], cwd=path, check=True)
    return path


@pytest.mark.parametrize("fmt", ["html", "csv", "json"])
def test_every_format_is_written(repo: Path, fmt: str, tmp_path: Path) -> None:
    out = tmp_path / f"r.{fmt}"
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", fmt, "-o", str(out)]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Bad�� Name" in text or "Bad\\ufffd\\ufffd Name" in text


@pytest.fixture(scope="module")
def on_branch(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("branch") / "r"
    subprocess.run(["git", "clone", "-q", str(repo), str(path)], check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    # Written into Git's files, not through `git update-ref`: a loose ref is a file
    # named by the ref, and macOS and Windows refuse a file name that is not UTF-8.
    packed = path / ".git" / "packed-refs"
    kept = [x for x in packed.read_bytes().splitlines(keepends=True) if not x.startswith(b"#")]
    packed.write_bytes(b"".join([*kept, head.encode() + b" refs/heads/b\xffr\n"]))
    (path / ".git" / "HEAD").write_bytes(b"ref: refs/heads/b\xffr\n")
    return path


@pytest.mark.parametrize("fmt", ["html", "csv", "json"])
def test_a_branch_whose_name_is_not_utf8_is_read(on_branch: Path, fmt: str, tmp_path: Path) -> None:
    out = tmp_path / f"r.{fmt}"
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(on_branch), "--format", fmt, "-o", str(out)]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    if fmt == "json":
        metadata = json.loads(out.read_text(encoding="utf-8"))["metadata"]
        assert metadata["analysed_branch"] == "b\ufffdr"
        assert metadata["total_commits"] == 1


def test_no_git_argument_holds_a_byte_windows_cannot_pass(
    on_branch: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ref read back from Git holds U+DCFF for the byte; Windows argv cannot carry it."""
    real = subprocess.Popen.__init__

    def refuse(self: subprocess.Popen[bytes], args: object, *rest: object, **kw: object) -> None:
        words = [args] if isinstance(args, str | bytes) else list(args)  # type: ignore[call-overload]
        assert not any(
            isinstance(w, str) and any("\udc80" <= c <= "\udcff" for c in w) for w in words
        ), words
        real(self, args, *rest, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess.Popen, "__init__", refuse)
    out = tmp_path / "r.json"

    result = CliRunner().invoke(app, ["generate", "--repo", str(on_branch), "-o", str(out)])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
