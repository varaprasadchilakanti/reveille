"""Integration tests for reports read from a shallow clone.

A shallow clone holds only the most recent commits, and Git walks it as if
that were the whole history. A depth-5 clone of a 571-commit repository
reported "5 commits over 2 days" with nothing saying anything was missing --
and CI checkouts are shallow by default. The report now says so, and says
that the window starts where the clone's history does.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from reveille.config import ReportConfig
from reveille.services.report import generate_report

_COMMITS = 6
_DEPTH = 2


def _git(args: list[str], cwd: Path, date: str | None = None) -> None:
    env = dict(os.environ)
    if date:
        env |= {
            "GIT_AUTHOR_NAME": "Alice",
            "GIT_AUTHOR_EMAIL": "alice@example.com",
            "GIT_COMMITTER_NAME": "Alice",
            "GIT_COMMITTER_EMAIL": "alice@example.com",
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture(scope="module")
def clones(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A six-commit repository and a depth-2 clone of it."""
    root = tmp_path_factory.mktemp("shallow")
    full = root / "full"
    full.mkdir()
    _git(["init", "-q", "-b", "main"], full)
    for index in range(_COMMITS):
        (full / f"f{index}.txt").write_text(f"{index}\n", encoding="utf-8")
        _git(["add", "-A"], full)
        _git(["commit", "-q", "-m", f"c{index}"], full, f"2024-03-{index + 1:02d}T10:00:00+00:00")
    shallow = root / "shallow"
    _git(["clone", "-q", f"--depth={_DEPTH}", f"file://{full}", str(shallow)], root)
    return full, shallow


def _json(repo: Path, out: Path) -> dict:
    config = ReportConfig(repo_path=repo, output_path=out, output_format="json", deterministic=True)
    return json.loads(generate_report(config)[0].read_text(encoding="utf-8"))


@pytest.mark.integration
class TestShallowClone:
    def test_positive_control_the_clone_is_short(
        self, clones: tuple[Path, Path], tmp_path: Path
    ) -> None:
        full, shallow = clones

        assert _json(full, tmp_path / "f.json")["metadata"]["total_commits"] == _COMMITS
        assert _json(shallow, tmp_path / "s.json")["metadata"]["total_commits"] == _DEPTH

    def test_provenance_says_so(self, clones: tuple[Path, Path], tmp_path: Path) -> None:
        full, shallow = clones

        assert _json(shallow, tmp_path / "s.json")["provenance"]["shallow_clone"] is True
        assert _json(full, tmp_path / "f.json")["provenance"]["shallow_clone"] is False

    def test_the_command_says_so(self, clones: tuple[Path, Path], tmp_path: Path) -> None:
        _, shallow = clones
        notices: list[str] = []
        generate_report(
            ReportConfig(repo_path=shallow, output_path=tmp_path / "s.html"),
            on_notice=notices.append,
        )

        assert any("shallow clone" in n and "--unshallow" in n for n in notices)

    def test_the_report_says_so(self, clones: tuple[Path, Path], tmp_path: Path) -> None:
        _, shallow = clones
        config = ReportConfig(repo_path=shallow, output_path=tmp_path / "s.html")
        text = " ".join(generate_report(config)[0].read_text(encoding="utf-8").split())

        assert "Shallow clone:" in text
        assert "starts where the clone's history does" in text

    def test_a_full_clone_says_nothing(self, clones: tuple[Path, Path], tmp_path: Path) -> None:
        full, _ = clones
        notices: list[str] = []
        config = ReportConfig(repo_path=full, output_path=tmp_path / "f.html")
        text = generate_report(config, on_notice=notices.append)[0].read_text(encoding="utf-8")

        assert not any("shallow" in n for n in notices)
        assert "Shallow clone:" not in text
