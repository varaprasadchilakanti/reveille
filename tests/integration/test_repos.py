# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`reveille repos`: one row per repository in a directory, naming no one (ADR 0026)."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_UNTIL = "2026-10-17"


def _repo(path: Path, *commits: tuple[str, str, str]) -> Path:
    """`commits` are (date, name, email)."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for n, (date, name, email) in enumerate(commits):
        (path / "f").write_text(f"{n}\n", encoding="utf-8")
        stamp = f"{date}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "C",
            "GIT_COMMITTER_EMAIL": "c@e.test",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{n}"], cwd=path, check=True, env=env)
    return path


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("ws") / "team"
    _repo(
        root / "api",
        ("2026-10-01", "Ana", "ana@corp.test"),
        ("2026-10-10", "Ben", "ben@corp.test"),
        ("2026-10-15", "dependabot[bot]", "bot@corp.test"),
    )
    _repo(root / "tools", ("2026-05-01", "Ana", "ana@corp.test"))
    _repo(root / "legacy", ("2024-01-10", "Carol", "carol@corp.test"))
    _repo(root / "bots-only", ("2026-10-12", "renovate[bot]", "r@corp.test"))
    root.joinpath("unborn").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root / "unborn", check=True)
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(root / "api"), str(root / "mirror.git")], check=True
    )
    refused = _repo(root / "refused", ("2026-10-01", "Dee", "dee@corp.test"))
    subprocess.run(["git", "config", "remote.origin.promisor", "true"], cwd=refused, check=True)
    # Inside a repository: a nested clone is not a row of its own.
    _repo(root / "api" / "vendor" / "inner", ("2026-10-01", "Eve", "eve@corp.test"))
    # Two levels down: found only with --depth 2.
    _repo(root / "group" / "deep", ("2026-09-01", "Fay", "fay@corp.test"))
    # A link to a repository elsewhere is not followed out of the directory.
    outside = _repo(root.parent / "outside", ("2026-10-01", "Gus", "gus@corp.test"))
    (root / "link").symlink_to(outside, target_is_directory=True)
    return root


def _repos(root: Path, *args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, ["repos", str(root), "--until", _UNTIL, *args])
    return result.exit_code, result.stdout, result.stderr


def _rows(root: Path, *args: str) -> dict[str, dict[str, object]]:
    code, out, err = _repos(root, "--format", "json", *args)
    assert code == ExitCode.SUCCESS, err
    return {row["path"]: row for row in json.loads(out)["repositories"]}


def test_each_repository_has_a_status_by_its_last_commit(workspace: Path) -> None:
    rows = _rows(workspace)

    assert {path: row["status"] for path, row in rows.items()} == {
        "api": "active",
        "bots-only": "active",
        "legacy": "dormant",
        "mirror.git": "active",
        "refused": "not read",
        "tools": "quiet",
        "unborn": "empty",
    }


def test_a_row_counts_people_and_automated_accounts_apart(workspace: Path) -> None:
    api = _rows(workspace)["api"]

    assert (api["commits"], api["people"], api["automated_accounts"]) == (3, 2, 1)
    assert api["last_commit"] == "2026-10-15"
    assert api["days_since_last_commit"] == 2


def test_no_name_or_address_reaches_any_format(workspace: Path) -> None:
    for fmt in ("text", "json", "markdown", "csv"):
        code, out, err = _repos(workspace, "--format", fmt)
        assert code == ExitCode.SUCCESS, err
        for who in ("Ana", "Ben", "Carol", "ana@", "ben@", "carol@", "dependabot"):
            assert who not in out, (fmt, who)


def test_a_refused_repository_is_a_row_with_its_reason_and_the_rest_are_read(
    workspace: Path,
) -> None:
    refused = _rows(workspace)["refused"]

    assert "partial clone" in str(refused["reason"])
    assert str(workspace) not in str(refused["reason"])


def test_a_nested_repository_is_not_a_row(workspace: Path) -> None:
    assert not any("inner" in path for path in _rows(workspace, "--depth", "3"))


def test_depth_reaches_a_repository_two_levels_down(workspace: Path) -> None:
    assert "group/deep" not in _rows(workspace)
    assert _rows(workspace, "--depth", "2")["group/deep"]["status"] == "active"


def test_a_symbolic_link_is_not_followed(workspace: Path) -> None:
    assert "link" not in _rows(workspace, "--depth", "3")


def test_an_exclusion_applies_in_every_repository(workspace: Path) -> None:
    rows = _rows(
        workspace, "--exclude-author", "renovate[bot]", "--exclude-author", "ben@corp.test"
    )

    assert rows["bots-only"]["status"] == "empty"
    assert rows["api"]["people"] == 1


def test_an_exclusion_that_matches_nowhere_is_said_once(workspace: Path) -> None:
    code, _, err = _repos(workspace, "--exclude-author", "nobody@nowhere.test")

    assert code == ExitCode.SUCCESS
    assert err.count("nobody@nowhere.test") == 1
    assert "in any repository" in err


def test_an_exclusion_that_matches_somewhere_is_not_reported(workspace: Path) -> None:
    _, _, err = _repos(workspace, "--exclude-author", "carol@corp.test")

    assert "matched no commits" not in err


def test_the_window_and_rules_are_stated(workspace: Path) -> None:
    code, out, _ = _repos(workspace, "--format", "json", "--days", "30")
    assert code == ExitCode.SUCCESS
    document = json.loads(out)

    assert document["window"] == {"since": "2026-09-18", "until": _UNTIL, "days": 30}
    assert document["rules"] == {"active_within_days": 30, "quiet_within_days": 365}
    assert document["totals"]["repositories"] == 7
    assert "does not add up to a number of people" in document["notice"]


def test_text_says_the_tally_and_the_rule(workspace: Path) -> None:
    _, out, _ = _repos(workspace)

    assert out.startswith("7 repositories in team, 2026-07-20 to 2026-10-17 (90 days): ")
    assert "3 active, 1 quiet, 1 dormant, 1 empty, 1 not read." in out
    assert "- tools: quiet, last commit 2026-05-01 (169 days ago)" in out


def test_a_directory_with_no_repository_answers_no(tmp_path: Path) -> None:
    code, _, err = _repos(tmp_path)

    assert code == ExitCode.NEGATIVE
    assert "No Git repository found" in err


def test_a_path_that_is_not_a_directory_cannot_run(tmp_path: Path) -> None:
    code, _, err = _repos(tmp_path / "missing")

    assert code == ExitCode.CANNOT_RUN
    assert "is not a directory" in err


def test_a_repository_name_cannot_become_a_spreadsheet_formula(tmp_path: Path) -> None:
    _repo(tmp_path / "=HYPERLINK(1)", ("2026-10-01", "Ana", "ana@corp.test"))

    code, out, err = _repos(tmp_path, "--format", "csv")

    assert code == ExitCode.SUCCESS, err
    first = next(csv.DictReader(io.StringIO(out)))
    assert first["path"] == "'=HYPERLINK(1)"


@pytest.mark.skipif(os.name != "posix", reason="a newline in a directory name")
def test_a_repository_name_cannot_add_a_line(tmp_path: Path) -> None:
    _repo(tmp_path / "a\n- fake: active", ("2026-10-01", "Ana", "ana@corp.test"))

    _, out, _ = _repos(tmp_path)

    assert "\n- fake: active" not in out


def test_a_repository_name_cannot_break_the_markdown_table(tmp_path: Path) -> None:
    _repo(tmp_path / "a|b", ("2026-10-01", "Ana", "ana@corp.test"))

    _, out, _ = _repos(tmp_path, "--format", "markdown")

    row = next(line for line in out.splitlines() if line.startswith("| `a"))
    # Seven cells take eight separators; a `|` from the name must be escaped.
    assert len(re.findall(r"(?<!\\)\|", row)) == 8
