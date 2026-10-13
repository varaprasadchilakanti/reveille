# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`reveille brief`: what changed since a point, in counts, naming nobody (ADR 0022)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


class _Repo:
    """A repository built commit by commit, with fixed dates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str, date: str = "2026-01-01T10:00:00+00:00", **who: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": who.get("name", "Ana Silva"),
            "GIT_AUTHOR_EMAIL": who.get("email", "ana@e.test"),
            "GIT_COMMITTER_NAME": who.get("name", "Ana Silva"),
            "GIT_COMMITTER_EMAIL": who.get("email", "ana@e.test"),
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
        return subprocess.run(
            ["git", *args], cwd=self.path, env=env, check=True, capture_output=True, text=True
        ).stdout

    def commit(self, path: str, date: str, **who: str) -> None:
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"{date}\n")
        self.git("add", "-A", date=date, **who)
        self.git("commit", "-qm", f"change {path}", date=date, **who)

    def tag(self, name: str) -> None:
        # A user's tag.gpgSign would need a key these repositories do not have.
        self.git("-c", "tag.gpgSign=false", "tag", name)


def _brief(repo: Path, *args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, ["brief", "--repo", str(repo), *args])
    return result.exit_code, result.stdout, result.stderr


def _json(repo: Path, *args: str) -> dict:
    code, out, err = _brief(repo, *args, "--format", "json")
    assert code == ExitCode.SUCCESS, err
    return json.loads(out)


@pytest.fixture
def released(tmp_path: Path) -> _Repo:
    """Two commits, a tag, then work by two people and a bot."""
    repo = _Repo(tmp_path / "r")
    repo.commit("src/core/a.py", "2026-01-01T10:00:00+00:00")
    repo.commit("docs/guide.md", "2026-01-02T10:00:00+00:00")
    repo.tag("v1.0")
    repo.commit("src/core/a.py", "2026-03-01T10:00:00+00:00")
    repo.commit("src/core/b.py", "2026-03-02T10:00:00+00:00", name="Ben Okafor", email="ben@e.test")
    repo.commit(
        "package-lock.json",
        "2026-03-03T10:00:00+00:00",
        name="dependabot[bot]",
        email="bot[bot]@users.noreply.github.com",
    )
    return repo


class TestFromARevision:
    def test_counts_only_what_came_after_the_tag(self, released: _Repo) -> None:
        brief = _json(released.path, "--from", "v1.0")

        assert brief["document"] == "brief"
        assert brief["totals"] == {
            "commits": 3,
            "people": 2,
            "automated_accounts": 1,
            "commits_with_co_authors": 0,
            "files_added": 2,
        }
        assert brief["point"]["from"] == "v1.0"
        assert brief["first_commit_date"] == "2026-03-01"

    def test_the_analysed_commit_is_the_next_point(self, released: _Repo) -> None:
        tip = released.git("rev-parse", "HEAD").strip()
        brief = _json(released.path, "--from", "v1.0")
        _, text, _ = _brief(released.path, "--from", "v1.0")

        assert brief["analysed_commit"] == tip
        assert f"reveille brief --from {tip[:12]}" in text
        code, _, err = _brief(released.path, "--from", tip)
        assert code == ExitCode.NEGATIVE, "nothing changed since the tip"
        assert "No commits since" in err

    def test_areas_and_types_are_counted(self, released: _Repo) -> None:
        brief = _json(released.path, "--from", "v1.0")

        assert brief["areas"]["list"][0] == {"area": "src/core", "commits": 2}
        types = {t["type"]: t["file_changes"] for t in brief["file_types"]["list"]}
        assert types == {".py": 2, "lock files": 1}

    def test_it_names_nobody(self, released: _Repo) -> None:
        for fmt in ("text", "json"):
            _, out, _ = _brief(released.path, "--from", "v1.0", "--format", fmt)
            for identity in ("Ana", "ana@", "Ben", "ben@", "dependabot", "bot[bot]"):
                assert identity not in out, f"{identity!r} in the {fmt} brief"

    def test_the_text_is_under_a_kilobyte_and_singular_when_one(self, released: _Repo) -> None:
        released.commit("x.txt", "2026-04-01T10:00:00+00:00")
        _, out, _ = _brief(released.path, "--from", "HEAD~1")

        assert len(out.encode()) < 1024
        assert "1 commit by 1 person" in out

    def test_two_runs_give_the_same_bytes(self, released: _Repo) -> None:
        first = _brief(released.path, "--from", "v1.0", "--format", "json")[1]
        second = _brief(released.path, "--from", "v1.0", "--format", "json")[1]

        assert first == second


class TestWhatCountsAsAdded:
    def test_a_modified_or_renamed_file_is_not_added(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path / "r")
        repo.commit("keep.txt", "2026-01-01T10:00:00+00:00")
        (repo.path / "old.txt").write_text("a fairly long line so the rename is detected\n" * 5)
        repo.git("add", "-A")
        repo.git("commit", "-qm", "old")
        repo.tag("start")
        repo.git("mv", "old.txt", "new.txt", date="2026-02-01T10:00:00+00:00")
        repo.git("commit", "-qm", "rename", date="2026-02-01T10:00:00+00:00")
        repo.commit("keep.txt", "2026-02-02T10:00:00+00:00")
        repo.commit("fresh.txt", "2026-02-03T10:00:00+00:00")

        assert _json(repo.path, "--from", "start")["totals"]["files_added"] == 1


class TestActiveAgain:
    @pytest.mark.parametrize(("gap_days", "listed"), [(90, True), (89, False)])
    def test_after_ninety_quiet_days(self, tmp_path: Path, gap_days: int, listed: bool) -> None:
        import datetime

        repo = _Repo(tmp_path / "r")
        before = datetime.datetime(2026, 1, 1, 10, tzinfo=datetime.UTC)
        repo.commit("lib/old/a.c", before.isoformat())
        repo.commit("src/b.c", (before + datetime.timedelta(days=1)).isoformat())
        repo.tag("point")
        repo.commit("lib/old/a.c", (before + datetime.timedelta(days=gap_days)).isoformat())

        brief = _json(repo.path, "--from", "point")

        assert (brief["active_again"]["list"] == ["lib/old"]) is listed


class TestTags:
    def test_a_tag_on_a_merge_commit_is_in_the_range(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path / "r")
        repo.commit("a.txt", "2026-01-01T10:00:00+00:00")
        repo.tag("v1")
        repo.git("switch", "-q", "-c", "topic")
        repo.commit("b.txt", "2026-01-02T10:00:00+00:00")
        repo.git("switch", "-q", "main")
        repo.commit("c.txt", "2026-01-03T10:00:00+00:00")
        repo.git("merge", "-q", "--no-ff", "-m", "merge", "topic", date="2026-01-04T10:00:00+00:00")
        repo.tag("v2")

        brief = _json(repo.path, "--from", "v1")

        assert brief["tags"]["list"] == ["v2"]
        assert brief["totals"]["commits"] == 2, "the merge itself is not counted (ADR 0001)"

    def test_an_area_name_cannot_drive_the_terminal(self, released: _Repo) -> None:
        """Git refuses control characters in a tag name, but not in a directory name."""
        released.commit("rel\x1b]8;;x\x07/f.txt", "2026-04-01T10:00:00+00:00")
        _, out, _ = _brief(released.path, "--from", "v1.0")

        assert "rel" in out, "positive control: the area is listed"
        assert "\x1b" not in out and "\x07" not in out


class TestTheDefaultPoint:
    def test_without_a_point_it_starts_at_the_latest_tag(self, released: _Repo) -> None:
        released.commit("src/core/c.py", "2026-03-04T10:00:00+00:00")
        released.tag("v1.1")
        released.commit("src/core/d.py", "2026-03-05T10:00:00+00:00")

        assert _json(released.path) == _json(released.path, "--from", "v1.1")

    def test_with_no_tag_it_cannot_run(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path / "untagged")
        repo.commit("a.txt", "2026-01-01T10:00:00+00:00")

        exit_code, out, err = _brief(repo.path)

        assert exit_code == ExitCode.CANNOT_RUN
        assert out == ""
        assert "no tag" in err and "--from" in err


class TestThePoint:
    def test_a_date_point(self, released: _Repo) -> None:
        brief = _json(released.path, "--since", "2026-03-02", "--deterministic")

        assert brief["point"] == {"since": "2026-03-02"}
        assert brief["totals"]["commits"] == 2

    def test_a_point_off_the_branch_is_stated(self, released: _Repo) -> None:
        released.git("switch", "-q", "-c", "side", "v1.0")
        released.commit("side.txt", "2026-05-01T10:00:00+00:00")
        released.git("switch", "-q", "main")

        code, out, err = _brief(released.path, "--branch", "side", "--from", "main")

        assert code == ExitCode.SUCCESS
        assert "is not an ancestor" in err
        assert "1 commit by 1 person" in out

    def test_an_exclusion_applies(self, released: _Repo) -> None:
        brief = _json(released.path, "--from", "v1.0", "--exclude-author", "ben@e.test")

        assert brief["totals"]["people"] == 1
        assert brief["totals"]["commits"] == 2

    @pytest.mark.parametrize(
        ("args", "code", "says"),
        [
            (["--from", "--output=x"], ExitCode.CANNOT_RUN, "beginning with '-'"),
            (["--from", "no-such-tag"], ExitCode.CANNOT_RUN, "does not name a commit"),
            (["--from", "v1.0", "--since", "2026-01-01"], ExitCode.CANNOT_RUN, "not both"),
            (["--since", "2027-01-01"], ExitCode.NEGATIVE, "No commits since"),
        ],
    )
    def test_what_it_refuses(self, released: _Repo, args: list[str], code: int, says: str) -> None:
        exit_code, out, err = _brief(released.path, *args)

        assert exit_code == code
        assert out == ""
        assert says in err
        assert not (released.path / "x").exists()
