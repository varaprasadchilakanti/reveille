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
        # The tagline is the first bold line under the title.
        taglines = [line for line in readme if line.startswith("**")][:1]
        assert taglines, "the README has no tagline"
        assert "Commit-history analytics" in taglines[0], (
            f"the README tagline no longer says what the tool does: {taglines[0]!r}"
        )

        pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        descriptions = [line for line in pyproject if line.startswith("description = ")]
        assert len(descriptions) == 1, f"expected one description, found {len(descriptions)}"
        assert "commit activity" in descriptions[0], (
            f"the package description no longer says what the tool does: {descriptions[0]!r}"
        )


@pytest.mark.unit
class TestTheGdprPositionIsStatedCorrectly:
    """The most serious documentation defect found in the legal review.

    `README.md` said `docs/COMPLIANCE.md` "records why GDPR ... do not engage".
    `COMPLIANCE.md` says the opposite, in the sentence a reader reaches first:
    commit author names and addresses are personal data under Art. 4(1), so the
    Regulation plainly engages. What does not attach is a controller or
    processor role for the maintainer.

    It was in the README, it is what a data protection officer or a procurement
    reviewer reads first, it asserted a legal conclusion that is wrong, and it
    was contradicted by the file it cited in the same sentence. Quoted back, it
    reads as either not understanding the Regulation or hoping nobody checks.
    """

    @staticmethod
    def _text(name: str) -> str:
        return " ".join((_ROOT / name).read_text(encoding="utf-8").split())

    def test_no_document_sweeps_the_gdpr_into_out_of_scope(self) -> None:
        """The sweeping claim is the source of the error, so it is the guard.

        "out of scope for every regime examined" is false as written, because
        the GDPR was examined and is not out of scope. The carved version --
        "every *other* regime examined" -- is the fix, so the guard looks for
        the sweep without the carve-out.
        """
        offenders = [
            name
            for name in ("docs/COMPLIANCE.md", "PRIVACY.md", "README.md", "SECURITY.md")
            if "out of scope for every regime examined" in self._text(name)
        ]
        assert not offenders, (
            f"{offenders} claim every examined regime is out of scope; the GDPR "
            "engages and the maintainer is simply not a controller or processor"
        )

    def test_the_readme_states_the_position_that_is_actually_true(self) -> None:
        """Deleting the wrong sentence would satisfy the guard above."""
        readme = self._text("README.md")
        assert "neither controller nor processor under the GDPR" in readme, (
            "the README no longer states the maintainer's actual GDPR position"
        )

    def test_llms_txt_does_not_list_the_gdpr_among_regimes_that_do_not_engage(self) -> None:
        """The index an assistant reads first said "why GDPR, the Cyber Resilience
        Act, ... do not engage" until 0.9.0, a sentence the README guard above
        could not see. An assistant repeating it would tell a user the opposite
        of what docs/COMPLIANCE.md concludes."""
        line = next(line for line in self._text("llms.txt").splitlines() if "COMPLIANCE.md" in line)
        assert "neither controller nor processor under the GDPR" in line
        assert "why GDPR," not in line

    def test_the_readme_does_not_send_users_to_the_contributor_notice(self) -> None:
        """`PRIVACY.md` is a notice for contributors, not for users of the tool.

        The README told users the report contains personal data and pointed
        them at `PRIVACY.md` for "who is responsible for what". That answer
        lives in `docs/COMPLIANCE.md`; a reader following the signpost did not
        reach it.
        """
        readme = self._text("README.md")
        assert "is a notice for *contributors to this project*" in readme


@pytest.mark.unit
class TestTheFuzzingClaimMatchesScorecard:
    """A checkable claim in a document that asks you to check it.

    `SECURITY.md` said Scorecard's Fuzzing check credits `atheris` for Python,
    and that an `atheris` stub would satisfy a string match. Both are false:
    `ossf/scorecard/docs/checks.md` lists Go, Haskell, JavaScript and
    TypeScript, Erlang, C# and F#, and mentions neither Python nor `atheris`.

    The passage is a set-piece about refusing to game a metric, which is what
    made it the one place an adversarial reviewer could say "you told me to
    verify your claims, so I did, and this one is false".
    """

    def test_the_false_python_claim_is_gone(self) -> None:
        security = " ".join((_ROOT / "SECURITY.md").read_text(encoding="utf-8").split())
        assert "for Python, `atheris` and nothing else" not in security

    def test_the_languages_scorecard_actually_supports_are_named(self) -> None:
        security = " ".join((_ROOT / "SECURITY.md").read_text(encoding="utf-8").split())
        assert "Python is not among them" in security
        for language in ("Go", "Haskell", "Erlang"):
            assert language in security, f"{language} is missing from the corrected list"


# Claims the project made and could not support, removed for 0.9.0. Matched
# over whitespace-normalised text, because prose wraps and a phrase split
# across two lines is still the same claim.
_UNSUPPORTED = (
    # DORA's guide defines its metrics for applications and services; it has
    # no explicit statement about individuals. SPACE is quoted from its abstract.
    "dora and space",
    # A paraphrase of SPACE that could not be checked against the paper (its
    # full text was unreachable on 2026-10-09); the abstract is quoted instead.
    "never be used on their own to reward",
    "reporting only anonymised, aggregate",
    # A reveille.toml naming .git/HEAD disproved it; the exact claim replaced it.
    "never modifies the repository",
    "production-grade",
    # Commit counts do not establish health.
    "repository health",
    "health metrics",
)


@pytest.mark.unit
class TestUnsupportedClaimsStayOut:
    """Each phrase below was once published and turned out not to be true."""

    @pytest.mark.parametrize("phrase", _UNSUPPORTED)
    def test_no_surface_makes_the_claim(self, phrase: str) -> None:
        offenders = [
            str(path.relative_to(_ROOT))
            for path in _surface_files()
            if phrase in " ".join(path.read_text(encoding="utf-8").lower().split())
        ]
        assert not offenders, f"{phrase!r} is back in: {offenders}"

    def test_the_matcher_sees_a_phrase_split_across_lines(self, tmp_path: pathlib.Path) -> None:
        """Positive control: wrapped prose must not slip past the guard."""
        sample = tmp_path / "s.md"
        sample.write_text("Both DORA and\nSPACE say so.\n", encoding="utf-8")
        assert "dora and space" in " ".join(sample.read_text(encoding="utf-8").lower().split())
