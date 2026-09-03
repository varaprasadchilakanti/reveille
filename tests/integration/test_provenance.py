"""Integration tests for report provenance, schema version, and determinism.

These run against a real Git repository, because the defects they guard
against are all invisible against a mock. In particular #22 -- the report
naming the wrong branch -- survived to v0.7.0 precisely because the only
tests that mentioned the field were unit fixtures hardcoding
`default_branch="main"`. A fixture that asserts its own input cannot catch a
field being computed from the wrong source.

The repository below is built with `main` checked out but the interesting
assertions are made while a *different* branch is current, which is the
condition under which the old behaviour diverged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from reveille.config import ReportConfig
from reveille.domain.models import SCHEMA_VERSION
from reveille.services.report import generate_report


@pytest.fixture(scope="module")
def two_branch_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository with `main` and a longer `feature` branch, `feature` checked out.

    `feature` carries one extra commit, so the two branches produce different
    commit counts. That difference is what makes a wrong branch detectable.
    """
    repo_path = tmp_path_factory.mktemp("two_branch_repo")

    def run(args: list[str], env_override: dict[str, str] | None = None) -> None:
        env = {**os.environ, **(env_override or {})}
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

    author = {
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
    }

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "alice@example.com"])
    run(["git", "config", "user.name", "Alice"])

    for i, date in enumerate(("2024-03-01T10:00:00+00:00", "2024-03-05T10:00:00+00:00")):
        (repo_path / f"file_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
        run(["git", "add", "-A"])
        run(
            ["git", "commit", "-m", f"feat: commit {i}"],
            {**author, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        )

    run(["git", "checkout", "-b", "feature"])
    (repo_path / "extra.py").write_text("y = 1\n", encoding="utf-8")
    run(["git", "add", "-A"])
    run(
        ["git", "commit", "-m", "feat: only on feature"],
        {
            **author,
            "GIT_AUTHOR_DATE": "2024-03-10T10:00:00+00:00",
            "GIT_COMMITTER_DATE": "2024-03-10T10:00:00+00:00",
        },
    )
    # Deliberately leave `feature` checked out.
    return repo_path


def _generate_json(repo: Path, out: Path, **kwargs: object) -> dict:
    config = ReportConfig(repo_path=repo, output_path=out, output_format="json", **kwargs)  # type: ignore[arg-type]
    written = generate_report(config)
    return json.loads(written[0].read_text(encoding="utf-8"))


@pytest.mark.integration
class TestAnalysedBranch:
    """Finding #22: the report must name the branch it actually analysed."""

    def test_reports_the_requested_branch_not_the_checkout(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """`--branch main` while `feature` is checked out must report `main`.

        This is the exact case that was wrong through v0.7.0: metadata was
        recomputed from the active branch and ignored the ref the analysis
        walked, so the HTML said "Branch: feature" for a report about `main`.
        """
        payload = _generate_json(two_branch_repo, tmp_path / "r.json", branch="main")

        assert payload["metadata"]["analysed_branch"] == "main"
        assert payload["provenance"]["filters"]["requested_branch"] == "main"

    def test_commit_count_confirms_the_named_branch_was_the_one_walked(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """The branch name must agree with the data, not merely be plausible.

        `feature` carries one commit `main` does not. If the counts were equal
        the previous test could pass while the wrong history was analysed.
        """
        on_main = _generate_json(two_branch_repo, tmp_path / "m.json", branch="main")
        on_feature = _generate_json(two_branch_repo, tmp_path / "f.json", branch="feature")

        assert on_main["metadata"]["total_commits"] == 2
        assert on_feature["metadata"]["total_commits"] == 3
        assert on_main["metadata"]["analysed_branch"] == "main"
        assert on_feature["metadata"]["analysed_branch"] == "feature"

    def test_falls_back_to_the_active_branch_when_none_requested(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """With no `--branch`, the analysed branch is the checkout -- and says so."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json")

        assert payload["metadata"]["analysed_branch"] == "feature"
        assert payload["provenance"]["filters"]["requested_branch"] is None


@pytest.mark.integration
class TestSchemaVersion:
    """Finding #6: a consumer must be able to detect a shape change."""

    def test_schema_version_is_the_first_key(self, two_branch_repo: Path, tmp_path: Path) -> None:
        """Ordering is part of the contract: decide before parsing the rest."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json")

        assert next(iter(payload)) == "schema_version"
        assert payload["schema_version"] == SCHEMA_VERSION


@pytest.mark.integration
class TestProvenance:
    """Finding #5: the artefact must state what it measured, and how."""

    def test_records_the_tool_and_the_exact_repository_state(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """Version and HEAD SHA are what make a report re-checkable."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json", branch="main")
        provenance = payload["provenance"]

        head = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=two_branch_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        assert provenance["head_sha"] == head
        assert provenance["reveille_version"]

    def test_records_filters_as_stated_parameters(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """A filtered report and an unfiltered one must be distinguishable.

        `analysis_since` records where the window began; `requested_since`
        records whether anyone asked for it. Without the second, "the full
        history, which starts in March" and "filtered to start in March" are
        the same document.
        """
        payload = _generate_json(
            two_branch_repo,
            tmp_path / "r.json",
            exclude_authors=["bot@example.com"],
            min_commits=2,
        )
        filters = payload["provenance"]["filters"]

        # A count, not the identifiers: --exclude-author exists to keep a
        # person out of the report, and writing their address into a labelled
        # provenance field would put it back.
        assert filters["exclude_authors_count"] == 1
        assert "bot@example.com" not in json.dumps(payload)
        assert filters["min_commits"] == 2
        assert filters["requested_since"] is None

    def test_records_the_ranking_weights_that_produced_the_scores(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """Scores are meaningless without the weights behind them.

        Opting in explicitly, because ranking is off by default from 0.8.0.
        """
        payload = _generate_json(two_branch_repo, tmp_path / "r.json", ranking_enabled=True)
        ranking = payload["provenance"]["ranking"]

        assert ranking["enabled"] is True
        assert set(ranking["weights"]) == {"commits", "lines", "consistency", "recency"}

    def test_omits_weights_when_ranking_is_disabled(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """Reporting weights that were never applied would be a false statement."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json", ranking_enabled=False)

        assert payload["provenance"]["ranking"]["enabled"] is False
        assert payload["provenance"]["ranking"]["weights"] is None


@pytest.mark.integration
class TestDeterministicOutput:
    """Finding #7: identical input must produce byte-identical output."""

    def test_json_is_byte_identical_across_runs(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """Two runs, same repository, same bytes."""
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        _generate_json(two_branch_repo, first, deterministic=True)
        _generate_json(two_branch_repo, second, deterministic=True)

        assert first.read_bytes() == second.read_bytes()

    def test_html_is_byte_identical_across_runs(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """The HTML report is the artefact people share, so it matters most."""
        first = tmp_path / "a.html"
        second = tmp_path / "b.html"
        for out in (first, second):
            generate_report(
                ReportConfig(repo_path=two_branch_repo, output_path=out, deterministic=True)
            )

        assert first.read_bytes() == second.read_bytes()

    def test_default_mode_is_not_deterministic_and_says_so(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """Without the flag the timestamp is real, and provenance records that.

        This is the control: if the default were already deterministic, the
        tests above would pass while proving nothing about the flag.
        """
        payload = _generate_json(two_branch_repo, tmp_path / "r.json")

        assert payload["provenance"]["deterministic"] is False

    def test_deterministic_pins_the_timestamp_to_the_repository(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """`generated_at` becomes a property of the input, not of the clock."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json", deterministic=True)

        assert payload["provenance"]["deterministic"] is True
        assert payload["metadata"]["generated_at"].startswith("2024-03-10")


@pytest.mark.integration
class TestRankingIsOptIn:
    """The contributor ranking is off unless explicitly requested."""

    def test_ranking_is_disabled_by_default(self, two_branch_repo: Path, tmp_path: Path) -> None:
        """A default report must not score or tier named individuals."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json")

        assert payload["provenance"]["ranking"]["enabled"] is False

    def test_ranking_fields_are_absent_rather_than_zeroed(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """An omitted key cannot be misread; `"tier": 0` can.

        Emitting sentinel values for something that was never computed hands a
        consumer a number it may treat as data.
        """
        payload = _generate_json(two_branch_repo, tmp_path / "r.json")
        contributor = payload["contributors"][0]

        for field in ("tier", "tier_designation", "composite_score", "percentile"):
            assert field not in contributor

    def test_opting_in_restores_the_ranking_fields(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """The control: the fields appear when asked for, so their absence means something."""
        payload = _generate_json(two_branch_repo, tmp_path / "r.json", ranking_enabled=True)
        contributor = payload["contributors"][0]

        assert payload["provenance"]["ranking"]["enabled"] is True
        for field in ("tier", "tier_designation", "composite_score", "percentile"):
            assert field in contributor

    def test_distribution_metrics_survive_the_ranking_being_off(
        self, two_branch_repo: Path, tmp_path: Path
    ) -> None:
        """The Gini coefficient describes the repository, not the people.

        It names nobody and is unchanged by who sits where in the order, which
        is why it stays in the default report when the per-person ranking does
        not.
        """
        payload = _generate_json(two_branch_repo, tmp_path / "r.json")

        assert "gini_coefficient" in payload["derived"]
        assert 0.0 <= payload["derived"]["gini_coefficient"] <= 1.0


@pytest.mark.integration
class TestAnalysisWindowIsTimezoneIndependent:
    """`--since` and `--until` must mean the same thing on every machine."""

    @pytest.fixture()
    def boundary_repo(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        """One commit at 22:00 UTC, which lands on a different local date."""
        repo = tmp_path_factory.mktemp("boundary")
        env = {
            "GIT_AUTHOR_NAME": "Alice",
            "GIT_AUTHOR_EMAIL": "alice@example.com",
            "GIT_COMMITTER_NAME": "Alice",
            "GIT_COMMITTER_EMAIL": "alice@example.com",
            "GIT_AUTHOR_DATE": "2024-06-10T22:00:00+00:00",
            "GIT_COMMITTER_DATE": "2024-06-10T22:00:00+00:00",
        }
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "a.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "boundary"],
            cwd=repo,
            check=True,
            env={**os.environ, **env},
        )
        return repo

    @pytest.mark.parametrize(
        "timezone", ["UTC", "Pacific/Auckland", "America/Los_Angeles", "Asia/Kolkata"]
    )
    def test_the_same_window_gives_the_same_answer_in_every_timezone(
        self, timezone: str, boundary_repo: Path, tmp_path: Path
    ) -> None:
        """Git parses a bare date in LOCAL time; this tool renders UTC.

        Before the boundaries were pinned to UTC, one commit at 22:00Z with
        `--since 2024-06-11` produced an empty window under UTC and under
        America/Los_Angeles, and a full report under Pacific/Auckland. Same
        repository, same flags, three different answers.
        """
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "reveille"),
                "generate",
                "--repo",
                str(boundary_repo),
                "--since",
                "2024-06-11",
                "-o",
                str(tmp_path / f"{timezone.replace('/', '_')}.html"),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "TZ": timezone},
        )

        # 2024-06-10T22:00Z is before the window in UTC, so every machine must
        # agree that there is nothing to report.
        assert result.returncode == 1, f"{timezone}: {result.stdout}{result.stderr}"

    @pytest.mark.parametrize("timezone", ["UTC", "Pacific/Auckland", "America/Los_Angeles"])
    def test_a_window_that_includes_the_commit_also_agrees(
        self, timezone: str, boundary_repo: Path, tmp_path: Path
    ) -> None:
        """The control: the fix must not simply exclude everything."""
        out = tmp_path / f"{timezone.replace('/', '_')}-in.html"
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "reveille"),
                "generate",
                "--repo",
                str(boundary_repo),
                "--since",
                "2024-06-10",
                "-o",
                str(out),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "TZ": timezone},
        )

        assert result.returncode == 0, f"{timezone}: {result.stdout}{result.stderr}"
        assert out.is_file()
