"""Unit tests for reveille.adapters.git_reader module-level helpers.

The GitReader class itself requires a real repository and is covered by
the integration suite. These tests exercise the numstat parser directly,
with no filesystem or subprocess access.
"""

from __future__ import annotations

import pytest

from reveille.adapters.git_reader import (
    _co_author_value,
    _expand_exclusions,
    _Mailmap,
    _match_key,
    _normalise_github_noreply,
    _parse_log_record,
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
    """Folding GitHub noreply addresses on the account number (ADR 0023)."""

    TABLE = _Mailmap(
        noreply_accounts={
            "111": "111+alice2@users.noreply.github.com",
            "222": "222+alice@users.noreply.github.com",
            "333": "333+carol@users.noreply.github.com",
        },
        noreply_usernames={"carol": "333+carol@users.noreply.github.com"},
    )

    def test_a_renamed_account_folds_to_its_current_username(self) -> None:
        for address in (
            "111+alice@users.noreply.github.com",
            "111+alice2@users.noreply.github.com",
        ):
            assert _normalise_github_noreply(address, self.TABLE) == (
                "111+alice2@users.noreply.github.com"
            )

    def test_two_accounts_that_used_one_username_stay_apart(self) -> None:
        assert _normalise_github_noreply("222+alice@users.noreply.github.com", self.TABLE) != (
            _normalise_github_noreply("111+alice@users.noreply.github.com", self.TABLE)
        )

    def test_a_legacy_address_joins_only_an_unambiguous_account(self) -> None:
        assert _normalise_github_noreply("carol@users.noreply.github.com", self.TABLE) == (
            "333+carol@users.noreply.github.com"
        )
        address = "alice@users.noreply.github.com"
        assert _normalise_github_noreply(address, self.TABLE) == address, "two accounts used it"

    def test_folding_is_idempotent(self) -> None:
        once = _normalise_github_noreply("111+alice@users.noreply.github.com", self.TABLE)
        assert _normalise_github_noreply(once, self.TABLE) == once

    @pytest.mark.parametrize(
        "address",
        [
            "alice@example.com",
            "12345+alice@users.noreply.gitlab.com",
            "team+alice@users.noreply.github.com",
            "999+nobody@users.noreply.github.com",
            "",
        ],
    )
    def test_anything_else_is_unchanged(self, address: str) -> None:
        assert _normalise_github_noreply(address, self.TABLE) == address

    def test_the_domain_matches_case_insensitively(self) -> None:
        assert _normalise_github_noreply("333+Carol@Users.NoReply.GitHub.Com", self.TABLE) == (
            "333+carol@users.noreply.github.com"
        )


@pytest.mark.unit
class TestResolveIdentity:
    """Tests for _resolve_identity, mailmap and noreply resolution combined."""

    def test_unmapped_ordinary_address_passes_through(self) -> None:
        assert _resolve_identity("Alice", "alice@example.com", _Mailmap()) == (
            "Alice",
            "alice@example.com",
        )

    def test_without_an_account_table_the_address_is_kept_whole(self) -> None:
        assert _resolve_identity("Alice", "99+alice@users.noreply.github.com", _Mailmap()) == (
            "Alice",
            "99+alice@users.noreply.github.com",
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
                ("daniel brown", "daniel@oldcorp.test"): ("Dan Brown", "dan@newcorp.test")
            }
        )
        assert _resolve_identity("Daniel Brown", "daniel@oldcorp.test", mailmap) == (
            "Dan Brown",
            "dan@newcorp.test",
        )

    def test_four_field_entry_ignored_when_the_name_differs(self) -> None:
        """The whole point of the form: a shared address, distinguished by name."""
        mailmap = _Mailmap(
            by_name_and_email={
                ("daniel brown", "shared@corp.test"): ("Dan Brown", "dan@newcorp.test")
            }
        )
        assert _resolve_identity("Erica Stone", "shared@corp.test", mailmap) == (
            "Erica Stone",
            "shared@corp.test",
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
            by_email={"shared@corp.test": ("Generic", "generic@corp.test")},
            by_name_and_email={
                ("daniel brown", "shared@corp.test"): ("Dan Brown", "dan@newcorp.test")
            },
        )
        assert _resolve_identity("Daniel Brown", "shared@corp.test", mailmap) == (
            "Dan Brown",
            "dan@newcorp.test",
        )
        # A different contributor on the same address still falls back.
        assert _resolve_identity("Erica Stone", "shared@corp.test", mailmap) == (
            "Generic",
            "generic@corp.test",
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


@pytest.mark.unit
def test_c1_controls_are_removed_from_names() -> None:
    """U+009B is CSI: some terminals obey it, given as UTF-8, like ESC [."""
    from reveille.adapters.git_reader import _strip_control_chars

    assert _strip_control_chars("Ana\x9b31m Silva\x85") == "Ana31m Silva"


@pytest.mark.unit
class TestCoAuthorValue:
    """Tests for _co_author_value, which reads one `Co-authored-by` value."""

    def test_a_name_and_address_are_split(self) -> None:
        assert _co_author_value("Ana Lima <ana@e.test>") == ("Ana Lima", "ana@e.test")

    @pytest.mark.parametrize("value", ["Ana <>", "Ana <a>b>", "Ana a@e.test>"])
    def test_an_empty_or_unbracketed_address_is_malformed(self, value: str) -> None:
        assert _co_author_value(value) is None


@pytest.mark.unit
def test_an_undatable_record_is_dropped_when_nobody_counts_it() -> None:
    """The count is optional; without it the record is still skipped, not raised."""
    sha = "a" * 40
    record = "\x1f".join([sha, "A", "a@e.test", "99999999999999999999", sha])

    assert _parse_log_record(record, _Mailmap(), set(), {sha}, set()) is None


@pytest.mark.unit
def test_a_four_field_entry_naming_someone_else_adds_nothing() -> None:
    mailmap = _Mailmap(
        by_name_and_email={("daniel brown", "daniel@old.test"): ("Dan Brown", "dan@new.test")}
    )

    assert _expand_exclusions(["Erica Stone"], mailmap) == {"erica stone"}


@pytest.mark.unit
class TestMatchKey:
    """Tests for _match_key, the form an exclusion is compared in."""

    def test_format_characters_spacing_form_and_case_are_ignored(self) -> None:
        assert _match_key(" ANA\u2060  Silva\u00ad ") == _match_key("Ana Silva")
        assert _match_key("Jose\u0301") == _match_key("Jos\u00e9")

    def test_the_comparison_is_bounded(self) -> None:
        """A crafted multi-megabyte name costs a bounded comparison, cut alike on both sides."""
        assert len(_match_key("a" * 5_000_000)) == 4096
        assert _match_key("a" * 4096 + "b") == _match_key("a" * 4096 + "c")


@pytest.mark.unit
def test_a_mailmap_entry_without_a_name_adds_only_its_address() -> None:
    mailmap = _Mailmap(
        by_email={"old@e.test": (None, "new@e.test")},
        by_name_and_email={("ana", "ana@old.test"): (None, "ana@new.test")},
    )

    assert _expand_exclusions(["OLD@e.test", "Ana"], mailmap) == {
        "old@e.test",
        "new@e.test",
        "ana",
        "ana@new.test",
    }
