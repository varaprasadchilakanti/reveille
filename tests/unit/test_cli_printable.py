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
    0x061C,
    0x200E,
    0x200F,
    0x2028,
    0x2029,
    *range(0x202A, 0x202F),
    *range(0x2066, 0x206A),
    0x200B,
    *range(0x2060, 0x2065),
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


@pytest.mark.unit
def test_an_undecodable_byte_is_shown_not_raised() -> None:
    """Git output read with surrogateescape holds lone surrogates; printing one raised."""
    assert _printable("a\udcffb") == "a\\xffb"


@pytest.mark.unit
def test_unicode_line_and_paragraph_separators_are_escaped() -> None:
    """Many readers break a line at U+2028 and U+2029, so one would add a line."""
    assert _printable(f"a{chr(0x2028)}b{chr(0x2029)}c") == "a\\u2028b\\u2029c"


@pytest.mark.unit
def test_tag_characters_and_the_byte_order_mark_are_escaped() -> None:
    """Tag characters spell ASCII a model reads and a person does not see on stderr."""
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "hi")
    assert _printable(f"a{hidden}\ufeffb") == "a\\U000e0068\\U000e0069\\ufeffb"
