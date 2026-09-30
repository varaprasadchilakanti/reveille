# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""What the project calls its own output, asserted.

Reveille does not produce a "performance report". It reports the volume
and regularity of commits, and `reveille capabilities` refuses to support
performance review, compensation, promotion, redundancy or hiring. For as
long as the promotional material said "performance report", the project
was advertising the thing its own machine-readable refusals disclaim.

The phrase also matters outside the project's own consistency. It is the
vocabulary of Annex III point 4(b) of Regulation (EU) 2024/1689 -- "to
monitor and evaluate the performance and behaviour of persons" -- and
Art. 3(12) makes the provider's own promotional and instructional
material evidence of a system's intended purpose. Reveille is not an AI
system, so Annex III is never reached; but a tagline is a poor place to
rest that on, and the phrase had nothing to recommend it beyond search
traffic.

Removed at 0.9.0 from eleven places: the PyPI description, the README
tagline and CLI reference, the `--help` text of the application and of
`generate`, the package docstring, the service docstring, the scaffolded
`reveille.toml`, and the sample configuration in both the README and the
User Guide. CHANGELOG 0.8.0 had already removed it from the report's own
subtitle, for the same reason, and this guard exists because a phrase
removed once came back.
"""

from __future__ import annotations

import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Everything a stranger or a package index reads. `CHANGELOG.md` and
# `docs/adr/` are excluded deliberately: both are historical records, the
# changelog states that the phrase was removed, and an ADR is immutable
# once merged. `tests/` is excluded because these guards quote the phrase
# in order to forbid it.
_SURFACES = (
    "pyproject.toml",
    "README.md",
    "SECURITY.md",
    "PRIVACY.md",
    "CONTRIBUTING.md",
    "llms.txt",
    "docs/USER_GUIDE.md",
    "docs/COMPLIANCE.md",
    "docs/ARCHITECTURE.md",
    "docs/PLAYBOOK.md",
)

# Language that would be evidence of an intended purpose the project
# disclaims. "machine learning" is deliberately absent: `COMPLIANCE.md`
# legitimately says the tool contains none, and a guard that cannot tell
# a denial from a claim would forbid the denial.
_FORBIDDEN = (
    "performance report",
    "ai-powered",
    "ai-driven",
    "smart scoring",
    "intelligent scoring",
)


def _surface_files() -> list[pathlib.Path]:
    """Return the promotional and instructional surface, plus the package."""
    files = [_ROOT / name for name in _SURFACES]
    files.extend(sorted((_ROOT / "src" / "reveille").rglob("*.py")))
    files.extend(sorted((_ROOT / "src" / "reveille" / "templates").rglob("*.j2")))
    return files


@pytest.mark.unit
class TestTheOutputIsNotCalledAPerformanceReport:
    """The phrase is absent from everything a reader is given."""

    def test_the_surface_list_is_real(self) -> None:
        """A guard over files that do not exist passes and means nothing."""
        missing = [str(path) for path in _surface_files() if not path.is_file()]
        assert not missing, f"the wording guard names files that do not exist: {missing}"

    @pytest.mark.parametrize("phrase", _FORBIDDEN)
    def test_no_surface_uses_the_phrase(self, phrase: str) -> None:
        offenders: list[str] = []
        for path in _surface_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if phrase in line.lower():
                    offenders.append(f"{path.relative_to(_ROOT)}:{number}")
        assert not offenders, (
            f"{phrase!r} appears in the material a reader is given: {offenders}. "
            "See this module's docstring for why it was removed."
        )

    def test_the_replacement_wording_is_actually_present(self) -> None:
        """The positive control.

        Deleting the tagline would satisfy every assertion above. What is
        asserted is a substitution, so the substitute has to be there.
        """
        readme = (_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        taglines = [line for line in readme if line.startswith("**A CLI tool")]
        assert len(taglines) == 1, f"expected one README tagline, found {len(taglines)}"
        assert "commit activity" in taglines[0], (
            f"the README tagline no longer says what the tool does: {taglines[0]!r}"
        )

        pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        descriptions = [line for line in pyproject if line.startswith("description = ")]
        assert len(descriptions) == 1, f"expected one description, found {len(descriptions)}"
        assert "commit activity" in descriptions[0], (
            f"the package description no longer says what the tool does: {descriptions[0]!r}"
        )
