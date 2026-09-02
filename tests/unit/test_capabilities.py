"""Unit tests for the self-description document.

The point of `reveille capabilities` is that a program can ask the tool what it
does instead of inferring it from prose. That is only worth anything if the
answer stays true, so the parts that *can* be derived from the running program
are derived, and the parts that cannot are pinned here.

The failure this guards against is specific and has already happened once in
this project: the README documented a `reveille version` subcommand that had
never existed, and survived a documentation branch and an audit because every
check compared text to text. A capability document written by hand would rot
the same way, only now a machine would be reading it.
"""

from __future__ import annotations

import json

import pytest
import typer.main

from reveille import __version__
from reveille.capabilities import (
    _EXIT_CODE_MEANINGS,
    build_capabilities,
    render_text,
)
from reveille.cli import ExitCode, app
from reveille.domain.models import SCHEMA_VERSION


@pytest.fixture()
def document() -> dict:
    """The assembled capability document."""
    return build_capabilities(app, ExitCode)


@pytest.mark.unit
class TestDerivedFactsCannotDrift:
    """Anything derivable from the program is derived, not restated."""

    def test_version_matches_the_package(self, document: dict) -> None:
        """A stale version here would misinform whatever reads it."""
        assert document["version"] == __version__

    def test_output_schema_version_matches_the_domain(self, document: dict) -> None:
        """The report's schema version is the one consumers parse against."""
        assert document["output_schema_version"] == SCHEMA_VERSION

    def test_every_registered_command_is_described(self, document: dict) -> None:
        """The command list is read from the Typer app, so it must be exact."""
        registered = set(typer.main.get_command(app).commands)
        described = {c["name"] for c in document["commands"]}

        assert described == registered

    def test_the_capabilities_command_describes_itself(self, document: dict) -> None:
        """A self-description that omits itself is incomplete by construction."""
        assert "capabilities" in {c["name"] for c in document["commands"]}

    def test_generate_options_include_the_real_flags(self, document: dict) -> None:
        """Options come from the live command, so the shipped flags appear."""
        generate = next(c for c in document["commands"] if c["name"] == "generate")
        flags = {flag for option in generate["options"] for flag in option["flags"]}

        assert {"--repo", "--output", "--format", "--deterministic"} <= flags


@pytest.mark.unit
class TestExitCodeContract:
    """Exit codes are a published contract, so the document must be complete."""

    def test_every_exit_code_has_a_meaning(self) -> None:
        """A new code must not be able to ship with an empty description.

        The meanings are a hand-written mapping rather than read from the enum:
        the per-member strings in `ExitCode` are bare expressions, not
        docstrings, so `member.__doc__` returns the *class* docstring and every
        code would carry identical, wrong text. This test is what keeps the
        mapping honest in exchange.
        """
        assert {m.name for m in ExitCode} == set(_EXIT_CODE_MEANINGS)

    def test_no_meaning_is_empty(self, document: dict) -> None:
        """An entry with no meaning is worse than an absent one."""
        assert all(entry["meaning"].strip() for entry in document["exit_codes"])

    def test_codes_are_reported_in_ascending_order(self, document: dict) -> None:
        """Stable ordering makes the document diffable across releases."""
        codes = [entry["code"] for entry in document["exit_codes"]]

        assert codes == sorted(codes)


@pytest.mark.unit
class TestStatedJudgements:
    """The written half must stay substantive, not decorative."""

    def test_the_cannot_list_is_not_empty(self, document: dict) -> None:
        """A tool that only advertises strengths is one an agent will misuse."""
        assert len(document["cannot"]) >= 5

    def test_every_entry_has_an_id_and_a_description(self, document: dict) -> None:
        """Each section is consumed programmatically, so shape matters."""
        for section in ("guarantees", "can", "cannot", "caveats"):
            for entry in document[section]:
                assert entry["id"], f"{section}: entry without an id"
                assert entry["description"].strip(), f"{section}/{entry['id']}: no text"

    def test_ids_are_unique_within_each_section(self, document: dict) -> None:
        """An id is a key; duplicates make the document ambiguous."""
        for section in ("guarantees", "can", "cannot", "caveats"):
            ids = [entry["id"] for entry in document[section]]
            assert len(ids) == len(set(ids)), f"{section} has duplicate ids"

    def test_the_measurement_disclaimer_is_present(self, document: dict) -> None:
        """This is the project's most important honesty commitment.

        The ranking measures volume and regularity of commits. If this ever
        stops being stated in the machine-readable description, an agent
        reading it has no way to learn the limit.
        """
        cannot = {entry["id"] for entry in document["cannot"]}

        assert "productivity-measurement" in cannot
        assert "individual-assessment" in cannot

    def test_the_offline_guarantee_is_stated(self, document: dict) -> None:
        """Load-bearing product behaviour, asserted elsewhere by e2e tests."""
        assert "offline" in {entry["id"] for entry in document["guarantees"]}


@pytest.mark.unit
class TestSerialisation:
    """The JSON form is the one a program consumes."""

    def test_document_is_json_serialisable(self, document: dict) -> None:
        """Anything unserialisable would break `--format json` at runtime."""
        assert json.loads(json.dumps(document)) == document

    def test_text_rendering_covers_every_section(self, document: dict) -> None:
        """A person reading the terminal must see the limits, not just the features."""
        rendered = render_text(document)

        assert "WHAT IT DOES NOT DO" in rendered
        assert "READ THE NUMBERS WITH THESE IN MIND" in rendered
        assert __version__ in rendered
