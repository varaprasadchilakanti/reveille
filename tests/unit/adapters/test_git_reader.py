"""Unit tests for reveille.adapters.git_reader module-level helpers.

The GitReader class itself requires a real repository and is covered by
the integration suite. These tests exercise the numstat parser directly,
with no filesystem or subprocess access.
"""

from __future__ import annotations

import pytest

from reveille.adapters.git_reader import _sum_numstat


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
