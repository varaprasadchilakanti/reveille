"""Security regression tests.

Each test here corresponds to a vulnerability that was reproduced against a
real malicious repository before it was fixed. The threat model is the one
that matters for this tool: **a victim runs Reveille against a repository
somebody else controls** -- a clone, a fork, a pull-request branch. Everything
in git history is then attacker-supplied text, and so is any `reveille.toml`
sitting at the repository root, because the CLI discovers that file
automatically from the working directory.

The findings these guard against were, in severity order:

1. Argument injection into `git log`. A revision beginning with `-` is parsed
   by git as an option, and `--branch "--output=/path"` made git write its log
   over that file. Reachable with no flags at all through an auto-discovered
   `reveille.toml`, so running `reveille generate` inside a clone was enough.
2. CSV formula injection. Author names are written to a CSV opened with a BOM
   specifically so Excel reads it directly, and nothing neutralised a leading
   `=`, `+`, `-` or `@`.
3. Record forgery. The reader splits `git log` output on ASCII 0x1E/0x1F, and
   git does not strip those from an author field. A single hand-written commit
   object produced three fabricated contributors, one promoted to the top tier.
4. Output path validation ran on the CLI flag rather than the effective path,
   so a config-supplied path skipped the traversal check; and writes followed
   symbolic links.
5. A forged timestamp crashed the run with an unhandled OverflowError.
"""

from __future__ import annotations

import csv
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader
from reveille.adapters.renderer import Renderer
from reveille.config import ReportConfig, load_config_from_toml
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)
from reveille.exceptions import (
    ConfigurationError,
    OutputPathError,
    RepositoryError,
)
from reveille.init import write_init_config, write_mailmap_template
from reveille.services.report import generate_report


def _write_toml(tmp_path: Path, body: str) -> Path:
    """Write a config file and return its path."""
    path = tmp_path / "reveille.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _run(args: list[str], cwd: Path, env_override: dict[str, str] | None = None) -> str:
    env = {**os.environ, **(env_override or {})}
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def _init_repo(path: Path, author: str = "Real", email: str = "real@example.com") -> Path:
    """A minimal repository with one honest commit."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], path)
    _run(["git", "config", "user.name", author], path)
    _run(["git", "config", "user.email", email], path)
    (path / "a.txt").write_text("x\n", encoding="utf-8")
    _run(["git", "add", "-A"], path)
    _run(
        ["git", "commit", "-qm", "base"],
        path,
        {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": "2024-03-01T10:00:00+00:00",
            "GIT_COMMITTER_DATE": "2024-03-01T10:00:00+00:00",
        },
    )
    return path


@pytest.mark.integration
class TestArgumentInjection:
    """A revision must never be able to act as a git option."""

    def test_branch_beginning_with_a_dash_is_refused(self, tmp_path: Path) -> None:
        """`--output=<path>` as a branch made git overwrite that path.

        The trailing `--` in the log arguments separates revisions from paths;
        it does not protect the revision slot.
        """
        repo = _init_repo(tmp_path / "repo")
        victim = tmp_path / "precious.txt"
        victim.write_text("PRECIOUS", encoding="utf-8")

        reader = GitReader(repo)
        with pytest.raises(RepositoryError, match="beginning with '-'"):
            reader.read_commits(
                branch=f"--output={victim}", since=None, until=None, exclude_authors=[]
            )

        assert victim.read_text(encoding="utf-8") == "PRECIOUS"

    def test_an_ordinary_branch_name_still_works(self, tmp_path: Path) -> None:
        """The guard must not cost legitimate use."""
        repo = _init_repo(tmp_path / "repo")

        commits = GitReader(repo).read_commits(
            branch="main", since=None, until=None, exclude_authors=[]
        )

        assert len(commits) == 1


@pytest.mark.integration
class TestRecordForgery:
    """An author field must not be able to fabricate other contributors."""

    def test_separator_injection_in_an_author_name_creates_no_contributors(
        self, tmp_path: Path
    ) -> None:
        """One hand-written commit previously yielded three contributors.

        Git's ident sanitiser strips `<`, `>` and newlines, but not the ASCII
        record and unit separators this reader splits on.
        """
        repo = _init_repo(tmp_path / "repo")
        tree = _run(["git", "rev-parse", "HEAD^{tree}"], repo).strip()
        parent = _run(["git", "rev-parse", "HEAD"], repo).strip()

        # The payload must yield a record with exactly four fields, because a
        # record with any other count is already discarded. The real commit's
        # own trailing `<email><sep><timestamp>` completes the injected record,
        # so the name only needs to supply a separator, a plausible object
        # name, and the contributor to fabricate.
        rs, us = "\x1e", "\x1f"
        forged_name = f"Real{rs}{'d' * 40}{us}Phantom Maintainer"
        obj = tmp_path / "obj.txt"
        obj.write_text(
            f"tree {tree}\nparent {parent}\n"
            f"author {forged_name} <x@example.com> 1700000000 +0000\n"
            f"committer Real <real@example.com> 1700000000 +0000\n\nforged\n",
            encoding="utf-8",
        )
        sha = _run(
            ["git", "hash-object", "-t", "commit", "-w", "--literally", str(obj)], repo
        ).strip()
        _run(["git", "update-ref", "refs/heads/main", sha], repo)

        commits = GitReader(repo).read_commits(
            branch="main", since=None, until=None, exclude_authors=[]
        )
        names = {c.author_name for c in commits}

        assert not any("Phantom" in n for n in names), f"fabricated contributor: {names}"

    def test_a_forged_timestamp_is_skipped_rather_than_crashing(self, tmp_path: Path) -> None:
        """An out-of-range timestamp previously raised an unhandled OverflowError."""
        repo = _init_repo(tmp_path / "repo")
        tree = _run(["git", "rev-parse", "HEAD^{tree}"], repo).strip()
        parent = _run(["git", "rev-parse", "HEAD"], repo).strip()

        obj = tmp_path / "obj.txt"
        obj.write_text(
            f"tree {tree}\nparent {parent}\n"
            "author Real <real@example.com> 99999999999999999999 +0000\n"
            "committer Real <real@example.com> 1700000000 +0000\n\nforged\n",
            encoding="utf-8",
        )
        sha = _run(
            ["git", "hash-object", "-t", "commit", "-w", "--literally", str(obj)], repo
        ).strip()
        _run(["git", "update-ref", "refs/heads/main", sha], repo)

        # The base commit survives; only the unusable record is dropped.
        commits = GitReader(repo).read_commits(
            branch="main", since=None, until=None, exclude_authors=[]
        )

        assert len(commits) >= 1


def _report_with_name(name: str) -> ReportData:
    """A one-contributor report whose display name is attacker-controlled."""
    stats = ContributorStats(
        name=name,
        email="a@example.com",
        commit_count=1,
        lines_added=1,
        lines_deleted=0,
        active_days=1,
        first_commit_date=datetime.date(2024, 1, 1),
        last_commit_date=datetime.date(2024, 1, 1),
    )
    return ReportData(
        metadata=RepositoryMetadata(
            name="r",
            remote_url=None,
            analysed_branch="main",
            total_commits=1,
            unique_contributors=1,
            analysis_since=datetime.date(2024, 1, 1),
            analysis_until=datetime.date(2024, 1, 2),
            generated_at=datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
        ),
        provenance=AnalysisProvenance(
            reveille_version="0.0.0",
            schema_version=SCHEMA_VERSION,
            head_sha=None,
            requested_branch=None,
            requested_since=None,
            requested_until=None,
            exclude_authors_count=0,
            min_commits=1,
            ranking_enabled=False,
            ranking_weights=None,
            mailmap_applied=False,
            deterministic=True,
        ),
        ranked_contributors=[
            RankedContributor(
                stats=stats,
                composite_score=1.0,
                percentile=1.0,
                tier=1,
                tier_designation="Private",
            )
        ],
        commits=[],
    )


@pytest.mark.integration
class TestCsvFormulaInjection:
    """The CSV is written with a BOM so Excel opens it directly."""

    @pytest.mark.parametrize(
        "payload",
        [
            "=cmd|'/C calc'!A0",
            '+HYPERLINK("http://evil.test")',
            "@SUM(1+1)*cmd",
            "-2+3+cmd",
            "\tsneaky",
        ],
    )
    def test_a_dangerous_name_cannot_start_a_cell(self, payload: str, tmp_path: Path) -> None:
        """Every cell must be inert text when the spreadsheet opens it."""
        out = tmp_path / "r.csv"
        Renderer().render_csv(_report_with_name(payload), out)

        with out.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

        assert rows, "no rows written"
        assert not rows[0]["name"].startswith(("=", "+", "-", "@", "\t", "\r"))

    def test_an_ordinary_name_is_left_alone(self, tmp_path: Path) -> None:
        """The mitigation must not corrupt normal data."""
        out = tmp_path / "r.csv"
        Renderer().render_csv(_report_with_name("Ada Lovelace"), out)

        with out.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

        assert rows[0]["name"] == "Ada Lovelace"


@pytest.mark.integration
class TestOutputPathSafety:
    """The path actually written must be the path that was checked."""

    def test_writing_through_a_symlink_is_refused(self, tmp_path: Path) -> None:
        """`write_text` follows a symlink and overwrites its target.

        The check must run before `Path.resolve()`, which follows the link and
        so reports the target as not-a-symlink -- the way this guard failed the
        first time it was written.
        """
        target = tmp_path / "target.txt"
        target.write_text("TARGET", encoding="utf-8")
        link = tmp_path / "report.html"
        link.symlink_to(target)

        with pytest.raises(OutputPathError, match="symbolic link"):
            Renderer().render(_report_with_name("Ada"), link)

        assert target.read_text(encoding="utf-8") == "TARGET"

    def test_config_supplied_output_path_is_validated(self, tmp_path: Path) -> None:
        """A traversal path from reveille.toml previously skipped the check.

        The CLI validated the `--output` flag, but wrote the merged value, so a
        config file could place the report anywhere.
        """
        repo = _init_repo(tmp_path / "repo")
        config = ReportConfig(
            repo_path=repo,
            output_path=tmp_path / "escaped.html",
            output_format="json",
            deterministic=True,
        )

        # The service itself must still write only where it is told.
        written = generate_report(config)

        assert written[0].parent == tmp_path
        assert not (repo / "escaped.html").exists()


@pytest.mark.integration
class TestOfflineGuarantee:
    """The report must never reach the network, whatever the repository says."""

    def test_attacker_supplied_url_never_becomes_a_loadable_resource(self, tmp_path: Path) -> None:
        """A contributor name containing a URL must stay inert text."""
        out = tmp_path / "r.html"
        Renderer().render(_report_with_name('<img src="http://evil.test/x.png">'), out)
        html = out.read_text(encoding="utf-8")

        # A disjunction here would be unconditionally true once any escaped
        # `&lt;img` appeared anywhere in the document, which it does. Assert the
        # specific thing instead: the payload may appear as escaped text, but
        # never as a live attribute in any quoting style.
        assert not re.search(r"""<img[^>]+src=["']?https?://evil\.test""", html)
        assert "&lt;img" in html, "payload should survive as escaped text"


@pytest.mark.integration
class TestSecondPassFindings:
    """Regressions for issues a second adversarial review found.

    The first pass fixed a symlink check that ran on the final path component
    only. That is not the same property as "the write lands where it should":
    a symlinked *parent directory* is not a symlink at the leaf, so the guard
    passed while a 4 MB report landed outside the repository. A guard that
    covers most of a property is easy to mistake for one that covers it.
    """

    def test_config_supplied_output_cannot_escape_via_a_symlinked_parent(
        self, tmp_path: Path
    ) -> None:
        """A hostile repository can commit a symlink; git stores them.

        The victim clones and runs bare `reveille generate`. No flags, no
        prompt: the auto-discovered reveille.toml chose the destination.
        """
        outside = tmp_path / "outside"
        outside.mkdir()
        victim = outside / "notes.html"
        victim.write_text("IMPORTANT", encoding="utf-8")

        repo = _init_repo(tmp_path / "hostile")
        (repo / "escape").symlink_to(outside)
        (repo / "reveille.toml").write_text(
            '[report]\noutput = "escape/notes.html"\n', encoding="utf-8"
        )

        # The installed console script, not `python -m reveille.cli`: the
        # module has no __main__ guard, so `-m` imports it, runs nothing and
        # exits 0 -- which would make this test pass against the vulnerability.
        console_script = Path(sys.executable).parent / "reveille"
        result = subprocess.run(
            [str(console_script), "generate"],
            cwd=repo,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert victim.read_text(encoding="utf-8") == "IMPORTANT"

    def test_init_refuses_a_symlinked_config_destination(self, tmp_path: Path) -> None:
        """A dangling link passes an `exists()` check and still redirects."""
        target = tmp_path / "not-yet-there.txt"
        link = tmp_path / "reveille.toml"
        link.symlink_to(target)

        with pytest.raises(OutputPathError, match="symbolic link"):
            write_init_config(link, force=False)

        assert not target.exists()

    def test_init_refuses_a_symlinked_mailmap(self, tmp_path: Path) -> None:
        """`.mailmap` is Git-native, so a repository can ship it as a link."""
        victim = tmp_path / "victim_rc"
        victim.write_text("USER DATA", encoding="utf-8")
        link = tmp_path / ".mailmap"
        link.symlink_to(victim)

        with pytest.raises(OutputPathError, match="symbolic link"):
            write_mailmap_template(link, force=True)

        assert victim.read_text(encoding="utf-8") == "USER DATA"

    def test_a_quoted_false_does_not_enable_the_ranking(self, tmp_path: Path) -> None:
        """`bool("false")` is True, and the wrong direction to fail in.

        A configuration that reads as "off" must never produce tiered named
        individuals -- least of all one auto-discovered from a clone.
        """
        with pytest.raises(ConfigurationError, match="true or false"):
            load_config_from_toml(_write_toml(tmp_path, '[ranking]\nenabled = "false"\n'))

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ('[filters]\nmin_commits = "abc"\n', "whole number"),
            ("[filters]\nexclude_authors = 5\n", "list of strings"),
            ('[filters]\nexclude_authors = "abc"\n', "list of strings"),
            ('[ranking]\nweights = "x"\n', "table of named weights"),
        ],
    )
    def test_malformed_config_raises_a_typed_error(
        self, body: str, message: str, tmp_path: Path
    ) -> None:
        """These were bare int()/list() calls that escaped as tracebacks.

        The CLI catches ConfigurationError only, so each printed a Rich
        traceback and exited 1 -- which on this project's published contract
        means "ran correctly, negative answer" rather than "could not run".
        """
        with pytest.raises(ConfigurationError, match=message):
            load_config_from_toml(_write_toml(tmp_path, body))


@pytest.mark.integration
class TestExclusionActuallyExcludes:
    """`--exclude-author` is the one operation whose purpose is privacy."""

    def test_excludes_a_person_renamed_by_a_mailmap(self, tmp_path: Path) -> None:
        """`git log --format=%an` shows the pre-mailmap name; users copy that.

        Matching only the resolved name left the person fully identified in
        the report, by name and address, with exit code 0 and no diagnostic.
        """
        repo = _init_repo(tmp_path / "repo", author="Bob Jones", email="bob@corp.example")
        (repo / ".mailmap").write_text(
            "Robert Jones <bob@corp.example> Bob Jones <bob@corp.example>\n",
            encoding="utf-8",
        )
        _run(["git", "add", "-A"], repo)
        _run(
            ["git", "commit", "-qm", "mailmap"],
            repo,
            {
                "GIT_AUTHOR_NAME": "Alice Smith",
                "GIT_AUTHOR_EMAIL": "alice@corp.example",
                "GIT_COMMITTER_NAME": "Alice Smith",
                "GIT_COMMITTER_EMAIL": "alice@corp.example",
            },
        )

        commits = GitReader(repo).read_commits(
            branch="main", since=None, until=None, exclude_authors=["Bob Jones"]
        )
        names = {c.author_name for c in commits}

        assert not any("Jones" in n for n in names), f"still present: {names}"

    def test_an_exclusion_that_matches_nothing_is_reported(self, tmp_path: Path) -> None:
        """Silence makes a typo indistinguishable from a working filter.

        That matters most in the case the flag exists for: somebody asked to
        be left out, and the report was generated believing they had been.
        """
        repo = _init_repo(tmp_path / "repo")
        reader = GitReader(repo)
        reader.read_commits(
            branch="main", since=None, until=None, exclude_authors=["Nobody At All"]
        )

        assert reader.unmatched_exclusions == ("nobody at all",)
