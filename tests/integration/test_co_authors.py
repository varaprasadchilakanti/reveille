"""Integration tests for co-authors read from trailers (ADR 0014).

Run against real repositories with real commit messages, because every
defect that matters here lives in how Git emits trailers: case, folding,
and a value crafted to forge a record for a different commit.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

import pytest

from reveille.config import ReportConfig
from reveille.services.report import generate_report

_BOT = "Copilot Autofix powered by AI <62310815+github-advanced-security[bot]@users.noreply.github.com>"


def _commit(repo: Path, author: str, email: str, message: str, day: int) -> None:
    (repo / f"f{day}.txt").write_text(f"{day}\n", encoding="utf-8")
    stamp = f"2026-03-{day:02d}T10:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    message_file = repo.parent / f"msg-{day}.txt"
    message_file.write_text(message, encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-q", "--cleanup=verbatim", "-F", str(message_file)],
        cwd=repo,
        check=True,
        env=env,
    )


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return repo


def _json(repo: Path, out: Path, **kwargs: object) -> dict:
    config = ReportConfig(
        repo_path=repo, output_path=out, output_format="json", deterministic=True, **kwargs
    )  # type: ignore[arg-type]
    return json.loads(generate_report(config)[0].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The shape of this project's own history: one maintainer, an
    automated co-author on two commits, plus a human pair on one."""
    repo = _repo(tmp_path_factory.mktemp("co"))
    _commit(repo, "Vara", "v@e.test", "fix: a\n\nCo-authored-by: " + _BOT + "\n", 1)
    _commit(repo, "Vara", "v@e.test", "fix: b\n\nco-authored-by: " + _BOT + "\n", 2)
    _commit(repo, "Vara", "v@e.test", "feat: c\n\nCo-authored-by: Ana Silva <ana@e.test>\n", 3)
    _commit(repo, "Vara", "v@e.test", "chore: d\n", 4)
    _commit(repo, "Ana Silva", "ana@e.test", "feat: e\n\nCo-authored-by: Vara <v@e.test>\n", 5)
    return repo


@pytest.mark.integration
class TestCoAuthorsAreAFact:
    def test_the_automated_co_author_is_reported(self, repo: Path, tmp_path: Path) -> None:
        payload = _json(repo, tmp_path / "r.json")
        only = {c["email"]: c for c in payload["co_authors_only"]}
        # Folded like an author address: the numeric noreply prefix is dropped.
        bot = only["github-advanced-security[bot]@users.noreply.github.com"]

        assert bot["co_authored_commits"] == 2, "the key is matched case-insensitively"
        assert bot["automated"] is True
        assert payload["derived"]["commits_with_co_authors"] == 4

    def test_an_author_credited_as_co_author_is_counted_on_their_row(
        self, repo: Path, tmp_path: Path
    ) -> None:
        payload = _json(repo, tmp_path / "r.json")
        rows = {c["email"]: c for c in payload["contributors"]}

        assert rows["ana@e.test"]["co_authored_commits"] == 1
        assert rows["v@e.test"]["co_authored_commits"] == 1
        assert "ana@e.test" not in {c["email"] for c in payload["co_authors_only"]}

    def test_authorship_figures_are_unchanged(self, repo: Path, tmp_path: Path) -> None:
        payload = _json(repo, tmp_path / "r.json")

        assert payload["metadata"]["total_commits"] == 5
        assert sum(c["commit_count"] for c in payload["contributors"]) == 5
        assert payload["derived"]["population_size"] == 2

    def test_the_report_states_it(self, repo: Path, tmp_path: Path) -> None:
        config = ReportConfig(repo_path=repo, output_path=tmp_path / "r.html", deterministic=True)
        text = " ".join(generate_report(config)[0].read_text(encoding="utf-8").split())

        assert "4 commits credit a co-author." in text
        assert "Credited only as co-author:" in text
        assert "Copilot Autofix powered by AI" in text

    def test_csv_carries_the_column(self, repo: Path, tmp_path: Path) -> None:
        config = ReportConfig(repo_path=repo, output_path=tmp_path / "r.html", output_format="csv")
        rows = list(csv.DictReader(generate_report(config)[0].open(encoding="utf-8-sig")))

        assert {r["email"]: r["co_authored_commits"] for r in rows} == {
            "v@e.test": "1",
            "ana@e.test": "1",
        }


@pytest.mark.integration
class TestTrailersAreReadSafely:
    def test_folded_names_are_unfolded(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _commit(repo, "A", "a@e.test", "x\n\nCo-authored-by: Long\n  Name <ln@e.test>\n", 1)

        (only,) = _json(repo, tmp_path / "r.json")["co_authors_only"]
        assert only["name"] == "Long Name"

    def test_crediting_yourself_is_ignored(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _commit(repo, "A", "a@e.test", "x\n\nCo-authored-by: A <A@E.TEST>\n", 1)

        payload = _json(repo, tmp_path / "r.json")
        assert payload["co_authors_only"] == []
        assert payload["derived"]["commits_with_co_authors"] == 0

    def test_a_trailer_cannot_credit_another_commit(self, tmp_path: Path) -> None:
        """A value holding the old record separator and a real hash forged a
        record for that commit when trailers were matched by hash alone."""
        from reveille.adapters.git_reader import GitReader

        repo = _repo(tmp_path)
        _commit(repo, "Victim", "victim@e.test", "honest\n", 1)
        victim = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        forged = f"x\x1e{victim}\x1fEvil <evil@e.test>"
        _commit(repo, "Mallory", "m@e.test", f"x\n\nCo-authored-by: {forged}\n", 2)

        commits = GitReader(repo).read_commits(
            branch="main", since=None, until=None, exclude_authors=[]
        )
        credited = {c.sha: c.co_authors for c in commits}

        assert credited[victim] == (), "a trailer in one commit credited another"

    def test_an_excluded_co_author_is_not_counted_and_the_filter_matched(
        self, repo: Path, tmp_path: Path
    ) -> None:
        from reveille.adapters.git_reader import GitReader

        reader = GitReader(repo)
        reader.read_commits(branch="main", since=None, until=None, exclude_authors=["ana@e.test"])

        assert reader.unmatched_exclusions == ()
        payload = _json(repo, tmp_path / "r.json", exclude_authors=["v@e.test"])
        assert "v@e.test" not in {c["email"] for c in payload["co_authors_only"]}

    def test_at_most_32_per_commit(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        trailers = "".join(f"Co-authored-by: P{i} <p{i}@e.test>\n" for i in range(50))
        _commit(repo, "A", "a@e.test", "x\n\n" + trailers, 1)

        assert len(_json(repo, tmp_path / "r.json")["co_authors_only"]) == 32

    def test_mailmap_applies(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo / ".mailmap").write_text("Ana Silva <ana@e.test> <old@e.test>\n", encoding="utf-8")
        _commit(repo, "A", "a@e.test", "x\n\nCo-authored-by: ana <old@e.test>\n", 1)

        (only,) = _json(repo, tmp_path / "r.json")["co_authors_only"]
        assert (only["name"], only["email"]) == ("Ana Silva", "ana@e.test")

    def test_below_min_commits_is_counted_not_named(self, repo: Path, tmp_path: Path) -> None:
        config = ReportConfig(
            repo_path=repo, output_path=tmp_path / "r.html", deterministic=True, min_commits=3
        )
        text = " ".join(generate_report(config)[0].read_text(encoding="utf-8").split())

        assert "Copilot Autofix" not in text
        assert "1 below --min-commits is not named." in text

    def test_no_finding_without_co_authors(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _commit(repo, "A", "a@e.test", "x\n", 1)
        config = ReportConfig(repo_path=repo, output_path=tmp_path / "r.html")
        text = generate_report(config)[0].read_text(encoding="utf-8")

        assert "credit a co-author" not in text
        assert "Credited only as co-author" not in text
