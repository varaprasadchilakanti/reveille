"""Integration tests for the opt-in "who changed each area" section (ADR 0013).

Run against a real repository, because what matters is end to end: the
section must be absent unless asked for, must follow ADR 0011 for people
below `--min-commits`, must never count an excluded author, and must leave
generated lock files out, as the hotspot chart does.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.config import ReportConfig, load_config_from_toml
from reveille.exceptions import ConfigurationError
from reveille.services.report import generate_report


def _commit(repo: Path, name: str, email: str, files: dict[str, str], day: int) -> None:
    for path, body in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    stamp = f"2026-03-{day:02d}T10:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", f"{name} {day}"], cwd=repo, check=True, env=env)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three people and a bot across `src/app/core`, `docs` and the root."""
    path = tmp_path_factory.mktemp("areas_repo")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day in range(1, 6):
        _commit(path, "Zoe", "zoe@e.test", {"src/app/core/a.py": f"{day}\n"}, day)
    _commit(path, "Amir", "amir@e.test", {"src/app/core/b.py": "b\n", "docs/x.md": "x\n"}, 6)
    _commit(path, "Amir", "amir@e.test", {"docs/y.md": "y\n"}, 7)
    _commit(path, "Rare", "rare@e.test", {"docs/z.md": "z\n"}, 8)
    _commit(path, "dependabot[bot]", "bot@e.test", {"poetry.lock": "l\n", "pyproject.toml": "p"}, 9)
    # A commit that changed nothing but a lock file: no area of work at all.
    _commit(path, "Amir", "amir@e.test", {"web/package-lock.json": "{}\n"}, 10)
    return path


def _json(repo: Path, out: Path, **kwargs: object) -> dict:
    config = ReportConfig(
        repo_path=repo, output_path=out, output_format="json", deterministic=True, **kwargs
    )  # type: ignore[arg-type]
    return json.loads(generate_report(config)[0].read_text(encoding="utf-8"))


def _areas(repo: Path, out: Path, **kwargs: object) -> dict[str, dict]:
    payload = _json(repo, out, area_authors_enabled=True, **kwargs)
    return {a["area"]: a for a in payload["areas"]}


@pytest.mark.integration
class TestOffByDefault:
    def test_no_area_data_without_the_flag(self, repo: Path, tmp_path: Path) -> None:
        payload = _json(repo, tmp_path / "r.json")

        assert "areas" not in payload
        assert payload["provenance"]["areas"] == {"enabled": False, "depth": None}

    def test_no_section_without_the_flag(self, repo: Path, tmp_path: Path) -> None:
        config = ReportConfig(repo_path=repo, output_path=tmp_path / "r.html", deterministic=True)
        html = generate_report(config)[0].read_text(encoding="utf-8")

        assert "Who Changed Each Area" not in html

    def test_the_ranking_does_not_switch_it_on(self, repo: Path, tmp_path: Path) -> None:
        payload = _json(repo, tmp_path / "r.json", ranking_enabled=True)

        assert "areas" not in payload


@pytest.mark.integration
class TestWithTheFlag:
    def test_areas_are_directories_cut_to_depth(self, repo: Path, tmp_path: Path) -> None:
        assert set(_areas(repo, tmp_path / "r.json")) == {"src/app/core", "docs", "(root)"}
        assert set(_areas(repo, tmp_path / "s.json", area_depth=1)) == {"src", "docs", "(root)"}

    def test_facts_per_area(self, repo: Path, tmp_path: Path) -> None:
        core = _areas(repo, tmp_path / "r.json")["src/app/core"]

        assert core["commits"] == 6
        assert core["authors"] == 2
        assert core["last_changed"] == "2026-03-06"
        assert [a["name"] for a in core["listed_authors"]] == ["Amir", "Zoe"]

    def test_no_count_per_person_anywhere(self, repo: Path, tmp_path: Path) -> None:
        for area in _areas(repo, tmp_path / "r.json").values():
            for person in area["listed_authors"] + area["listed_automated_accounts"]:
                assert set(person) == {"name", "email"}

    def test_a_lock_file_is_not_an_area_of_work(self, repo: Path, tmp_path: Path) -> None:
        areas = _areas(repo, tmp_path / "r.json")
        root = areas["(root)"]

        assert "web" not in areas, "a directory changed only through its lock file"

        # The bot's commit still changed pyproject.toml, so it is there once.
        assert root["commits"] == 1
        assert root["automated_accounts"] == 1
        assert [a["name"] for a in root["listed_automated_accounts"]] == ["dependabot[bot]"]

    def test_below_min_commits_counted_not_named(self, repo: Path, tmp_path: Path) -> None:
        docs = _areas(repo, tmp_path / "r.json", min_commits=2)["docs"]

        assert docs["authors"] == 2
        assert docs["not_listed"] == 1
        assert [a["name"] for a in docs["listed_authors"]] == ["Amir"]

    def test_an_excluded_author_is_neither_counted_nor_named(
        self, repo: Path, tmp_path: Path
    ) -> None:
        docs = _areas(repo, tmp_path / "r.json", exclude_authors=["rare@e.test"])["docs"]

        assert docs["authors"] == 1
        assert docs["not_listed"] == 0

    def test_the_section_is_rendered(self, repo: Path, tmp_path: Path) -> None:
        config = ReportConfig(
            repo_path=repo,
            output_path=tmp_path / "r.html",
            deterministic=True,
            area_authors_enabled=True,
        )
        text = " ".join(generate_report(config)[0].read_text(encoding="utf-8").split())

        assert "Who Changed Each Area" in text
        assert "<code>src/app/core</code>: 6 commits by 2 authors." in text
        assert "Authors: Amir and Zoe." in text
        assert "not who knows or owns it" in text

    def test_deterministic_output_stays_deterministic(self, repo: Path, tmp_path: Path) -> None:
        first = _json(repo, tmp_path / "a.json", area_authors_enabled=True)
        second = _json(repo, tmp_path / "b.json", area_authors_enabled=True)

        assert first == second


@pytest.mark.integration
class TestConfiguration:
    def test_the_toml_section(self, tmp_path: Path) -> None:
        path = tmp_path / "reveille.toml"
        path.write_text("[areas]\nenabled = true\ndepth = 2\n", encoding="utf-8")

        assert load_config_from_toml(path) == {"area_authors_enabled": True, "area_depth": 2}

    @pytest.mark.parametrize("body", ['enabled = "false"', "depth = true", 'depth = "2"'])
    def test_a_quoted_or_wrong_value_is_refused(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / "reveille.toml"
        path.write_text(f"[areas]\n{body}\n", encoding="utf-8")

        with pytest.raises(ConfigurationError):
            load_config_from_toml(path)

    def test_the_command_line(self, repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "r.html"
        result = CliRunner().invoke(
            app,
            [
                "generate",
                "--repo",
                str(repo),
                "-o",
                str(out),
                "--area-authors",
                "--area-depth",
                "1",
            ],
        )

        assert result.exit_code == ExitCode.SUCCESS, result.stderr
        html = " ".join(out.read_text(encoding="utf-8").split())
        assert "<code>src</code>" in html
        assert "up to 1 level deep" in html

    def test_a_depth_of_zero_is_refused_plainly(self, repo: Path, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app,
            ["generate", "--repo", str(repo), "-o", str(tmp_path / "r.html"), "--area-depth", "0"],
        )

        assert result.exit_code == ExitCode.CANNOT_RUN
        assert "--area-depth" in result.stderr
        assert "pydantic" not in result.stderr


@pytest.mark.integration
def test_non_ascii_and_quoted_paths_are_read_as_written(tmp_path: Path) -> None:
    """Git quotes such paths in numstat ("src/na\\303\\257ve/\\303\\274.py"),
    and the quoted form became an area and a hotspot of its own, with a
    stray quote: one directory shown twice."""
    from reveille.adapters.git_reader import GitReader

    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    _commit(path, "A", "a@e.test", {"src/naïve/ü.py": "1\n", "src/plain.py": "1\n"}, 1)
    _commit(path, "A", "a@e.test", {'src/say "hi".py': "1\n"}, 2)
    (path / "src/naïve/ü.py").rename(path / "src/naïve/ö.py")
    _commit(path, "A", "a@e.test", {}, 3)

    reader = GitReader(path)
    reader.read_commits(branch="main", since=None, until=None, exclude_authors=[], area_depth=2)
    files = {f.path for f in reader.file_stats}
    areas = {a.area for a in reader.area_activity}

    assert "src/naïve/ü.py" in files
    assert "src/naïve/ö.py" in files, "the rename's destination, decoded"
    assert 'src/say "hi".py' in files
    assert not any(f.startswith('"') or "\\3" in f for f in files)
    assert areas == {"src/naïve", "src"}
