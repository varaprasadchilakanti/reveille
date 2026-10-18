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
import sys
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


def test_an_unmatched_exclusion_in_capitals_is_still_said(workspace: Path) -> None:
    """The reader compares in lower case; the values given must not be."""
    _, _, err = _repos(
        workspace, "--exclude-author", "Nobody@Nowhere.TEST", "--exclude-author", "CAROL@corp.test"
    )

    assert "in any repository for: Nobody@Nowhere.TEST" in err
    assert "CAROL" not in err


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


def test_repositories_are_read_side_by_side_and_listed_in_order(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first repository found takes longest, so a pool that listed rows as
    they finished would put it last."""
    import threading
    import time

    from reveille.domain.repositories import RepositoryActivity
    from reveille.services import report

    in_flight, most = 0, 0
    lock = threading.Lock()
    found = sorted(report.find_repositories(workspace, 1)[0])

    def slow_row(path: Path, relative: str, *_: object) -> tuple[RepositoryActivity, set[str]]:
        nonlocal in_flight, most
        with lock:
            in_flight += 1
            most = max(most, in_flight)
        time.sleep(0.05 * (len(found) - found.index(path)))
        with lock:
            in_flight -= 1
        return RepositoryActivity(relative, "not read", reason="slow"), set()

    monkeypatch.setattr(report, "_repository_row", slow_row)
    monkeypatch.setattr(report, "_repository_workers", lambda: 4)
    _, out, _ = _repos(workspace, "--format", "json")

    listed = [row["path"] for row in json.loads(out)["repositories"]]
    assert listed == [p.relative_to(workspace).as_posix() for p in found]
    assert 1 < most <= 4, most


def test_at_most_four_repositories_are_read_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from reveille.services import report

    monkeypatch.setattr(report, "_usable_cpus", lambda: 64)
    assert report._repository_workers() == 4
    monkeypatch.setattr(report, "_usable_cpus", lambda: None)
    assert report._repository_workers() == 1


@pytest.mark.skipif(not hasattr(os, "sched_setaffinity"), reason="no affinity mask")
def test_a_process_pinned_to_one_cpu_reads_one_at_a_time() -> None:
    """A container or CI job limited to one CPU still sees every CPU in `os.cpu_count()`."""
    code = (
        "import os; os.sched_setaffinity(0, {sorted(os.sched_getaffinity(0))[0]}); "
        "from reveille.services import report; "
        "print(os.cpu_count(), report._repository_workers())"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    machine, workers = (int(n) for n in done.stdout.split())

    assert workers == 1, (machine, workers)


def test_each_rows_warnings_come_in_the_rows_order(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The warnings name no repository, so their order is what places them."""
    import logging
    import time

    from reveille.domain.repositories import RepositoryActivity
    from reveille.services import report

    found = sorted(report.find_repositories(workspace, 1)[0])
    logger = logging.getLogger("reveille.adapters.git_reader")

    def slow_row(path: Path, relative: str, *_: object) -> tuple[RepositoryActivity, set[str]]:
        time.sleep(0.05 * (len(found) - found.index(path)))
        logger.warning("first of %s", relative)
        logger.warning("second of %s", relative)
        return RepositoryActivity(relative, "not read", reason="slow"), set()

    monkeypatch.setattr(report, "_repository_row", slow_row)
    monkeypatch.setattr(report, "_repository_workers", lambda: 4)
    _, _, err = _repos(workspace, "--format", "json")

    names = [p.relative_to(workspace).as_posix() for p in found]
    wanted = [f"{which} of {name}" for name in names for which in ("first", "second")]
    places = [err.find(json.dumps(line)[1:-1]) for line in wanted]
    assert -1 not in places, err
    assert places == sorted(places), err
    assert logger.parent is not None
    assert not any(h.filters for h in logging.getLogger("reveille").handlers), "filter left on"


@pytest.mark.parametrize("until", ["2024-01-31", "2024-02-01", "2024-04-15", "2024-12-31"])
def test_a_dormant_repositorys_last_date_is_what_a_full_read_gives(
    tmp_path: Path, until: str
) -> None:
    """Dates out of order: the last commit made is not the latest dated."""
    import datetime

    from reveille.adapters.git_reader import GitReader
    from reveille.exceptions import EmptyRepositoryError

    path = _repo(
        tmp_path / "skewed",
        ("2024-03-01", "Ana", "ana@corp.test"),
        ("2024-05-01", "Ben", "ben@corp.test"),
        ("2024-02-01", "Carol", "carol@corp.test"),
    )
    end = datetime.date.fromisoformat(until)
    reader = GitReader(path)
    try:
        full = max(c.timestamp.date() for c in reader.read_commits(None, None, end, []))
    except EmptyRepositoryError:  # no commit on or before `end`
        full = None

    assert GitReader(path).last_commit_date(end) == full


def test_a_dormant_repository_is_not_read_whole_for_one_date(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reveille.adapters.git_reader import GitReader

    whole: list[object] = []
    real = GitReader.read_commits

    def spy(self: GitReader, branch: object, since: object, *args: object, **kw: object) -> object:
        if since is None:
            whole.append(self)
        return real(self, branch, since, *args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(GitReader, "read_commits", spy)
    rows = _rows(workspace)

    assert rows["legacy"]["last_commit"] == "2024-01-10"
    assert whole == []
