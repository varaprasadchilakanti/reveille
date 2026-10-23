# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A byte Git gave that is not UTF-8 is `\\xNN` in JSON, as in text, never a lone surrogate."""

from __future__ import annotations

import json

import pytest

from reveille.undecoded import as_escapes, json_text

pytestmark = pytest.mark.unit

_UNDECODED = b"caf\xff.txt".decode("utf-8", "surrogateescape")


def test_an_undecoded_byte_is_written_as_its_hexadecimal_escape() -> None:
    assert as_escapes(_UNDECODED) == "caf\\xff.txt"
    assert as_escapes(b"\x80".decode("utf-8", "surrogateescape")) == "\\x80"


def test_a_surrogate_no_byte_maps_to_is_written_as_its_code_point() -> None:
    assert as_escapes("a\ud800b") == "a\\ud800b"


def test_keys_and_nested_values_are_escaped_and_other_values_kept() -> None:
    document = {_UNDECODED: [_UNDECODED, ("t", 1)], "n": None, "b": True, "f": 1.5}

    assert as_escapes(document) == {
        "caf\\xff.txt": ["caf\\xff.txt", ["t", 1]],
        "n": None,
        "b": True,
        "f": 1.5,
    }


def test_the_json_holds_no_lone_surrogate_and_says_the_byte() -> None:
    text = json_text({"path": _UNDECODED, "emoji": "\U0001f600"}, indent=2)

    assert "\\udc" not in text
    assert json.loads(text) == {"path": "caf\\xff.txt", "emoji": "\U0001f600"}


def test_a_document_without_one_is_what_json_dumps_writes() -> None:
    document = {"path": "a\\udcff", "list": ["é", 1]}

    assert json_text(document, indent=2) == json.dumps(document, indent=2)


def test_a_json_message_on_stderr_writes_the_byte_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import logging

    from reveille import cli

    monkeypatch.setitem(cli._stderr_json, "on", True)
    cli._err(f"Warning: {_UNDECODED} is odd")
    cli._StderrHandler().emit(logging.makeLogRecord({"msg": _UNDECODED, "levelname": "WARNING"}))

    lines = capsys.readouterr().err.splitlines()
    assert [json.loads(line) for line in lines] == [
        {"level": "warning", "message": "caf\\xff.txt is odd"},
        {"level": "warning", "message": "caf\\xff.txt"},
    ]
