# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A tag named like the checked-out branch does not stand in for it.

Git reads `refs/tags/<name>` before `refs/heads/<name>`, so a tag `main` on an
old commit made every figure describe that commit, while the report still
named the branch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    for n in range(3):
        (tmp_path / "f.txt").write_text(str(n), encoding="utf-8")
        _git(tmp_path, "add", "f.txt")
        _git(tmp_path, "commit", "-qm", f"c{n}")
    _git(tmp_path, "tag", "main", "HEAD~2")
    assert _git(tmp_path, "rev-list", "--count", "main") == "1", "positive control"
    return tmp_path


def _json(*args: str) -> dict:
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return dict(json.loads(result.stdout))


def test_the_counts_are_the_branch(repo: Path) -> None:
    assert _json("summary", "--repo", str(repo))["totals"]["commits"] == 3
    assert _json("who-changed", "f.txt", "--repo", str(repo))["commits"] == 3
    assert _json("brief", "--since", "2000-01-01", "--repo", str(repo))["totals"]["commits"] == 3


def test_the_report_names_the_branch_and_pins_its_tip(repo: Path) -> None:
    report = _json("generate", "-q", "-o", "-", "--repo", str(repo))

    assert report["metadata"]["total_commits"] == 3
    assert report["metadata"]["analysed_branch"] == "main"
    assert report["provenance"]["head_sha"] == _git(repo, "rev-parse", "HEAD")


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.parametrize(
    ("args", "count"),
    [
        (("summary",), lambda d: d["totals"]["commits"]),
        (("who-changed", "f.txt"), lambda d: d["commits"]),
        (("brief", "--since", "2000-01-01"), lambda d: d["totals"]["commits"]),
        (("generate", "-q", "-o", "-"), lambda d: d["metadata"]["total_commits"]),
    ],
)
def test_an_explicit_branch_is_the_branch(repo: Path, args: tuple[str, ...], count: object) -> None:
    """`--branch main` names a branch; Git's advice for the clash is the full ref (gitrevisions)."""
    _git(repo, "checkout", "-q", "--detach", "HEAD~1")  # so the active branch cannot answer

    code, out, err = _run(*args, "--branch", "main", "--repo", str(repo), "--format", "json")

    assert code == ExitCode.SUCCESS, err
    assert count(json.loads(out)) == 3  # type: ignore[operator]
    assert "names both a branch and a tag; the branch is read" in err
    assert "--branch refs/tags/main" in err


def test_the_tag_is_read_when_asked_for_in_full(repo: Path) -> None:
    code, out, err = _run(
        "summary", "--branch", "refs/tags/main", "--repo", str(repo), "--format", "json"
    )

    assert code == ExitCode.SUCCESS, err
    assert json.loads(out)["totals"]["commits"] == 1
    assert "names both" not in err


def test_a_name_that_is_only_a_tag_is_still_read(repo: Path) -> None:
    _git(repo, "tag", "only-a-tag", "HEAD~1")

    code, out, err = _run(
        "summary", "--branch", "only-a-tag", "--repo", str(repo), "--format", "json"
    )

    assert code == ExitCode.SUCCESS, err
    assert json.loads(out)["totals"]["commits"] == 2
    assert "names both" not in err


def test_a_revision_suffix_is_left_to_git(repo: Path) -> None:
    """`main~1` is no ref, so it is Git's to read, tag first: the tag is the root commit.

    `show-ref --verify` matches only an exact ref; `rev-parse` would have read
    `refs/heads/main~1` as the branch's parent and made it look like a branch.
    """
    code, _, err = _run("summary", "--branch", "main~1", "--repo", str(repo), "--format", "json")

    assert code == ExitCode.CANNOT_RUN, err
    assert "'main~1' does not name a commit" in err, err
