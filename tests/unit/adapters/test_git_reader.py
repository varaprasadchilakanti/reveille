"""Unit tests for reveille.adapters.git_reader module-level helpers.

The GitReader class itself requires a real repository and is covered by
the integration suite. These tests exercise the numstat parser directly,
with no filesystem or subprocess access.
"""

from __future__ import annotations

import pytest

from reveille.adapters.git_reader import (
    _Mailmap,
    _normalise_github_noreply,
    _resolve_identity,
    _sum_numstat,
)


@pytest.mark.unit
class TestSumNumstat:
    """Tests for _sum_numstat, the `git log --numstat` block parser."""

    def test_empty_block_totals_zero(self) -> None:
        assert _sum_numstat("") == (0, 0)

    def test_whitespace_only_block_totals_zero(self) -> None:
        assert _sum_numstat("\n\n") == (0, 0)

    def test_single_line_returns_its_counts(self) -> None:
        assert _sum_numstat("3\t1\tmodule_a.py") == (3, 1)

    def test_multiple_lines_are_summed(self) -> None:
        block = "3\t1\tmodule_a.py\n10\t4\tmodule_b.py\n0\t7\tmodule_c.py"
        assert _sum_numstat(block) == (13, 12)

    def test_leading_blank_line_is_ignored(self) -> None:
        # git emits a blank line between the format header and the
        # numstat block, so the parser always receives one.
        assert _sum_numstat("\n5\t2\tmodule_a.py") == (5, 2)

    def test_binary_file_contributes_zero(self) -> None:
        # Binary files report a literal '-' for both counts.
        assert _sum_numstat("-\t-\tlogo.png") == (0, 0)

    def test_binary_and_text_files_mix_correctly(self) -> None:
        block = "-\t-\tlogo.png\n4\t2\tmodule_a.py"
        assert _sum_numstat(block) == (4, 2)

    def test_rename_path_form_is_parsed(self) -> None:
        # A rename renders the path as `old => new` in a single field.
        assert _sum_numstat("2\t1\tsrc/{old.py => new.py}") == (2, 1)

    def test_malformed_line_is_skipped(self) -> None:
        block = "not-a-numstat-line\n6\t3\tmodule_a.py"
        assert _sum_numstat(block) == (6, 3)

    def test_negative_counts_are_not_credited(self) -> None:
        # git never emits these; isdigit() rejects them rather than
        # letting a malformed value subtract from the total.
        assert _sum_numstat("-4\t-2\tmodule_a.py") == (0, 0)


@pytest.mark.unit
class TestNormaliseGithubNoreply:
    """Tests for _normalise_github_noreply, the GitHub address folder."""

    def test_prefixed_address_loses_its_numeric_id(self) -> None:
        assert (
            _normalise_github_noreply("140685918+alice@users.noreply.github.com")
            == "alice@users.noreply.github.com"
        )

    def test_legacy_address_is_unchanged(self) -> None:
        # Already canonical; normalising must be idempotent.
        assert (
            _normalise_github_noreply("alice@users.noreply.github.com")
            == "alice@users.noreply.github.com"
        )

    def test_normalisation_is_idempotent(self) -> None:
        once = _normalise_github_noreply("1+alice@users.noreply.github.com")
        assert _normalise_github_noreply(once) == once

    def test_ordinary_address_is_unchanged(self) -> None:
        assert _normalise_github_noreply("alice@example.com") == "alice@example.com"

    def test_bot_username_with_brackets_is_handled(self) -> None:
        # dependabot commits under 49699333+dependabot[bot]@users.noreply.github.com
        assert (
            _normalise_github_noreply("49699333+dependabot[bot]@users.noreply.github.com")
            == "dependabot[bot]@users.noreply.github.com"
        )

    def test_domain_match_is_case_insensitive(self) -> None:
        assert (
            _normalise_github_noreply("42+Alice@Users.NoReply.GitHub.Com")
            == "Alice@users.noreply.github.com"
        )

    def test_other_noreply_domain_is_unchanged(self) -> None:
        # Only GitHub's domain is folded; a lookalike must pass through.
        address = "12345+alice@users.noreply.gitlab.com"
        assert _normalise_github_noreply(address) == address

    def test_prefix_without_digits_is_unchanged(self) -> None:
        address = "team+alice@users.noreply.github.com"
        assert _normalise_github_noreply(address) == address

    def test_empty_string_is_unchanged(self) -> None:
        assert _normalise_github_noreply("") == ""


@pytest.mark.unit
class TestResolveIdentity:
    """Tests for _resolve_identity, mailmap and noreply resolution combined."""

    def test_unmapped_ordinary_address_passes_through(self) -> None:
        assert _resolve_identity("Alice", "alice@example.com", _Mailmap()) == (
            "Alice",
            "alice@example.com",
        )

    def test_unmapped_noreply_address_is_normalised(self) -> None:
        assert _resolve_identity("Alice", "99+alice@users.noreply.github.com", _Mailmap()) == (
            "Alice",
            "alice@users.noreply.github.com",
        )

    def test_mailmap_entry_on_raw_address_wins(self) -> None:
        mailmap = _Mailmap(
            by_email={"99+alice@users.noreply.github.com": ("Alice Real", "alice@example.com")}
        )
        assert _resolve_identity("Alice", "99+alice@users.noreply.github.com", mailmap) == (
            "Alice Real",
            "alice@example.com",
        )

    def test_mailmap_entry_on_normalised_address_also_matches(self) -> None:
        # An entry written against the legacy form catches the prefixed form.
        mailmap = _Mailmap(
            by_email={"alice@users.noreply.github.com": ("Alice Real", "alice@example.com")}
        )
        assert _resolve_identity("Alice", "99+alice@users.noreply.github.com", mailmap) == (
            "Alice Real",
            "alice@example.com",
        )

    def test_raw_mailmap_entry_takes_precedence_over_normalised(self) -> None:
        mailmap = _Mailmap(
            by_email={
                "99+alice@users.noreply.github.com": ("Raw Match", "raw@example.com"),
                "alice@users.noreply.github.com": ("Normalised Match", "norm@example.com"),
            }
        )
        assert _resolve_identity("Alice", "99+alice@users.noreply.github.com", mailmap) == (
            "Raw Match",
            "raw@example.com",
        )

    def test_mailmap_lookup_is_case_insensitive_on_the_raw_address(self) -> None:
        mailmap = _Mailmap(by_email={"alice@example.com": ("Alice Real", "alice@example.com")})
        assert _resolve_identity("Alice", "ALICE@example.com", mailmap) == (
            "Alice Real",
            "alice@example.com",
        )

    def test_mailmap_target_that_is_a_noreply_address_is_left_alone(self) -> None:
        # The mailmap states intent explicitly; it is not second-guessed.
        mailmap = _Mailmap(
            by_email={"alice@example.com": ("Alice", "7+alice@users.noreply.github.com")}
        )
        assert _resolve_identity("Alice", "alice@example.com", mailmap) == (
            "Alice",
            "7+alice@users.noreply.github.com",
        )


@pytest.mark.unit
class TestResolveIdentityFourFieldForm:
    """Tests for the four-field form, which matches on name and email together."""

    def test_four_field_entry_matches_when_name_and_email_agree(self) -> None:
        mailmap = _Mailmap(
            by_name_and_email={
                ("daniel brown", "daniel@oldcorp.com"): ("Dan Brown", "dan@newcorp.com")
            }
        )
        assert _resolve_identity("Daniel Brown", "daniel@oldcorp.com", mailmap) == (
            "Dan Brown",
            "dan@newcorp.com",
        )

    def test_four_field_entry_ignored_when_the_name_differs(self) -> None:
        """The whole point of the form: a shared address, distinguished by name."""
        mailmap = _Mailmap(
            by_name_and_email={
                ("daniel brown", "shared@corp.com"): ("Dan Brown", "dan@newcorp.com")
            }
        )
        assert _resolve_identity("Erica Stone", "shared@corp.com", mailmap) == (
            "Erica Stone",
            "shared@corp.com",
        )

    def test_four_field_matching_is_case_insensitive_on_both_fields(self) -> None:
        mailmap = _Mailmap(
            by_name_and_email={
                ("commit name", "commit@email.xx"): ("Proper Name", "proper@email.xx")
            }
        )
        assert _resolve_identity("CoMmIt NaMe", "CoMmIt@EmAiL.xX", mailmap) == (
            "Proper Name",
            "proper@email.xx",
        )

    def test_four_field_entry_wins_over_an_email_only_entry(self) -> None:
        """Git prefers the most specific match; name plus email is more specific."""
        mailmap = _Mailmap(
            by_email={"shared@corp.com": ("Generic", "generic@corp.com")},
            by_name_and_email={
                ("daniel brown", "shared@corp.com"): ("Dan Brown", "dan@newcorp.com")
            },
        )
        assert _resolve_identity("Daniel Brown", "shared@corp.com", mailmap) == (
            "Dan Brown",
            "dan@newcorp.com",
        )
        # A different contributor on the same address still falls back.
        assert _resolve_identity("Erica Stone", "shared@corp.com", mailmap) == (
            "Generic",
            "generic@corp.com",
        )


@pytest.mark.unit
class TestResolveIdentityEmailOnlyForm:
    """Tests for the email-only form, which replaces the address but keeps the name."""

    def test_commit_name_is_preserved(self) -> None:
        mailmap = _Mailmap(by_email={"commit@example.com": (None, "proper@example.com")})
        assert _resolve_identity("Alice", "commit@example.com", mailmap) == (
            "Alice",
            "proper@example.com",
        )

    def test_each_commit_keeps_its_own_name(self) -> None:
        mailmap = _Mailmap(by_email={"shared@example.com": (None, "proper@example.com")})
        assert _resolve_identity("Alice", "shared@example.com", mailmap)[0] == "Alice"
        assert _resolve_identity("Bob", "shared@example.com", mailmap)[0] == "Bob"
