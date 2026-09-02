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
        """The command list is read from the Typer app, so it must be exact.

        Checked against an independent literal as well as against the app.
        Comparing only `set(get_command(app).commands)` to a document built
        from that same expression is `set(X) == set(X)`: if Click restructured
        and both sides became empty, the test would pass while the document
        told a program this tool has no commands.
        """
        registered = set(typer.main.get_command(app).commands)
        described = {c["name"] for c in document["commands"]}

        assert described == registered
        assert described == {"generate", "validate", "init", "capabilities", "help"}

    def test_a_broken_introspection_raises_rather_than_emptying(self) -> None:
        """An empty command list is never a true answer, so it must not be one.

        `getattr(group, "commands", {})` would have produced exactly that: a
        valid-looking document, exit 0, claiming no commands exist.
        """
        import typer.main as typer_main

        from reveille.capabilities import _commands

        class _NoCommands:
            pass

        original = typer_main.get_command
        typer_main.get_command = lambda _app: _NoCommands()  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError, match="Could not read the command list"):
                _commands(app)
        finally:
            typer_main.get_command = original

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


@pytest.mark.unit
class TestGuaranteeTextsSayWhatTheyClaim:
    """The document's own premise is that a machine can trust it.

    `capabilities.py` states that the guarantees are "the ones worth checking
    against, because each is asserted by a test". That was true of their
    *presence* and false of their *content*: the existing tests check ids,
    non-emptiness and uniqueness, so `no-telemetry` could be rewritten to
    "We collect anonymous usage data." and `repository-modification` to
    "Freely alters repository history." with the whole suite green.

    These assert the substance. They are deliberately about meaning rather
    than exact wording -- the text may be improved, but it may not be
    inverted.
    """

    def _guarantee(self, guarantee_id: str) -> str:
        document = build_capabilities(app, ExitCode)
        matches = [g for g in document["guarantees"] if g["id"] == guarantee_id]
        assert matches, f"guarantee {guarantee_id!r} is missing from the document"
        return matches[0]["description"].lower()

    def test_offline_denies_network_use(self) -> None:
        text = self._guarantee("offline")
        assert "no network call" in text
        assert "no remote resource" in text

    def test_read_only_analysis_denies_modifying_the_repository(self) -> None:
        text = self._guarantee("read-only-analysis")
        assert "never modifies the repository" in text
        # And still discloses the one command that does write, which the
        # earlier wording of llms.txt and this module both once omitted.
        assert "init" in text

    def test_no_telemetry_denies_collection(self) -> None:
        text = self._guarantee("no-telemetry")
        assert "nothing is reported" in text
        for claim in ("we collect", "usage data", "analytics", "telemetry is sent"):
            assert claim not in text, f"no-telemetry guarantee asserts the opposite: {claim!r}"

    def test_self_contained_output_denies_external_dependencies(self) -> None:
        text = self._guarantee("self-contained-output")
        assert "single file" in text
        assert "no external dependency" in text

    def test_no_guarantee_promises_something_the_tool_does_not_do(self) -> None:
        """A blanket sweep for claims this tool must never make."""
        document = build_capabilities(app, ExitCode)
        blob = " ".join(g["description"].lower() for g in document["guarantees"])
        for forbidden in (
            "measures productivity",
            "measures contribution",
            "bus factor",
            "uploads",
            "phones home to",
        ):
            assert forbidden not in blob, f"a guarantee claims {forbidden!r}"


@pytest.mark.unit
class TestDerivedFactsAreActuallyDerived:
    """The module's premise is that derived facts cannot drift. Test the seams."""

    def test_output_formats_come_from_the_config_type(self) -> None:
        """This was a hardcoded literal that nothing cross-checked."""
        from typing import get_args

        from reveille.config import OutputFormat

        document = build_capabilities(app, ExitCode)
        assert document["output_formats"] == [str(f) for f in get_args(OutputFormat)]

    def test_output_formats_are_not_empty(self) -> None:
        assert build_capabilities(app, ExitCode)["output_formats"]

    def test_exit_codes_match_the_enum(self) -> None:
        document = build_capabilities(app, ExitCode)
        reported = {entry["code"] for entry in document["exit_codes"]}
        assert reported == {member.value for member in ExitCode}

    def test_schema_version_matches_the_models(self) -> None:
        from reveille.domain.models import SCHEMA_VERSION

        assert build_capabilities(app, ExitCode)["output_schema_version"] == SCHEMA_VERSION

    def test_version_matches_the_package(self) -> None:
        import reveille

        assert build_capabilities(app, ExitCode)["version"] == reveille.__version__
