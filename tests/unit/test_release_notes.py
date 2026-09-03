# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The release notes are read from the CHANGELOG, not retyped.

`.github/scripts/release_notes.py` turns a tag into the title and body
the publish workflow gives to `gh release create`. It exists so the
GitHub Release and the changelog cannot disagree, which is the reason
the heading carries a theme at all.

It is executed here against this repository's real CHANGELOG, so a
heading that stops matching the convention fails the build rather than
producing an untitled release at tag time -- by which point, with
release immutability enabled, the notes are one of the few things still
editable and the tag is not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / ".github" / "scripts" / "release_notes.py"
_CHANGELOG = _ROOT / "CHANGELOG.md"


def _run(tag: str, flag: str, changelog: Path | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            tag,
            flag,
            "--changelog",
            str(changelog or _CHANGELOG),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode, (completed.stdout + completed.stderr).strip()


@pytest.mark.unit
class TestAgainstThisRepositorysChangelog:
    """The file that will actually be read at release time."""

    def test_the_title_is_the_tag_and_the_heading_theme(self) -> None:
        code, title = _run("v0.8.0", "--title")
        assert code == 0, title
        assert title == "v0.8.0 — Security Hardening, Apache-2.0, and a Rebuilt Report"

    def test_the_title_matches_the_heading_in_the_file(self) -> None:
        """Not a hardcoded string: read the heading and compare."""
        heading = next(
            line
            for line in _CHANGELOG.read_text(encoding="utf-8").splitlines()
            if line.startswith("## [0.8.0]")
        )
        theme = heading.split("—")[-1].strip()
        _, title = _run("v0.8.0", "--title")
        assert title.endswith(theme)

    def test_the_body_is_that_version_and_stops_at_the_next(self) -> None:
        code, body = _run("v0.8.0", "--body")
        assert code == 0
        assert "### Added" in body
        assert "## [0.7.0]" not in body, "the body ran into the previous release"
        assert "## [Unreleased]" not in body

    def test_a_heading_without_a_theme_degrades_to_the_tag(self) -> None:
        """Releases before the convention must stay describable."""
        code, title = _run("v0.7.0", "--title")
        assert code == 0
        assert title == "v0.7.0"

    def test_every_released_version_can_be_described(self) -> None:
        """A version in the file that the script cannot read is a trap.

        It would surface at tag time, when the tag is already immutable.
        """
        import re

        versions = re.findall(
            r"^## \[(\d+\.\d+\.\d+)\]", _CHANGELOG.read_text(encoding="utf-8"), re.MULTILINE
        )
        assert versions, "no released versions found in the CHANGELOG"
        for version in versions:
            code, output = _run(f"v{version}", "--title")
            assert code == 0, f"v{version} cannot be described: {output}"


@pytest.mark.unit
class TestItFailsLoudlyRatherThanQuietly:
    """An untitled release is worse than a failed job."""

    def test_an_absent_version_is_an_error(self) -> None:
        code, output = _run("v99.99.99", "--title")
        assert code != 0
        assert "no CHANGELOG heading" in output

    def test_the_error_says_why_it_matters(self) -> None:
        _, output = _run("v99.99.99", "--title")
        assert "release notes are read from it" in output

    def test_a_heading_with_no_date_is_not_matched(self, tmp_path: Path) -> None:
        """The convention is version, date, theme. Two of three is not it."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [1.0.0] — Some Theme\n\nbody\n", encoding="utf-8")
        code, _ = _run("v1.0.0", "--title", changelog)
        assert code != 0
