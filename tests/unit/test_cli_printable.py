"""The terminal-safety table escapes exactly the characters it names.

It replaced a regular expression whose control-character range CodeQL read
as a mistake (py/overly-large-range). The set is pinned here, so neither a
missing block nor an extra one passes.
"""

from __future__ import annotations

import pytest

from reveille.cli import _printable

_ESCAPED = {
    *range(0x00, 0x09),
    *range(0x0B, 0x20),
    *range(0x7F, 0xA0),
    *range(0x202A, 0x202F),
    *range(0x2066, 0x206A),
}


@pytest.mark.unit
def test_exactly_the_named_blocks_are_escaped() -> None:
    escaped = {
        code
        for code in range(0x2100)
        if not 0xD800 <= code <= 0xDFFF and _printable(chr(code)) != chr(code)
    }
    assert escaped == _ESCAPED


@pytest.mark.unit
def test_newline_tab_and_text_pass_through() -> None:
    assert _printable("a\tb\nc é ü") == "a\tb\nc é ü"


@pytest.mark.unit
def test_an_escape_sequence_is_shown_not_obeyed() -> None:
    assert _printable("\x1b[2J‮evil") == "\\x1b[2J\\u202eevil"
