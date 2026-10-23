# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

r"""A suggested command runs as shown, and a refused value reads as text output writes it.

Text output writes a byte that is not UTF-8 as `\xNN`. Quoted by `shlex`, a
path holding one gave a command the shell took literally; `repr` gave
`'\udcff'` where every other line says `\xff`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from reveille.undecoded import quoted, shell_word

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("plain", "plain"),
        ("a b", "'a b'"),
        ("wt\udcff", "$'wt\\xff'"),
        ("it's\udcff", "$'it\\'s\\xff'"),
        ("back\\\udcff", "$'back\\\\\\xff'"),
        ("nl\n\udcff", "$'nl\\x0a\\xff'"),
    ],
)
def test_shell_word(text: str, word: str) -> None:
    assert shell_word(text) == word


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("name", [b"wt\xff", b"it's \xfe\\x"])
def test_bash_reads_the_word_back_as_the_same_bytes(tmp_path: Path, name: bytes) -> None:
    try:
        target = Path(os.fsdecode(bytes(tmp_path) + b"/" + name))
        target.mkdir()
    except (OSError, UnicodeEncodeError):
        pytest.skip("this file system refuses the name")

    script = f"printf %s {shell_word(str(target))}"
    out = subprocess.run(["bash", "-c", script], check=True, capture_output=True).stdout

    assert out == bytes(target)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("a\udcffb", "'a\\xffb'"),
        ("\udc80\udcff", "'\\x80\\xff'"),
        ("\\udcff", "'\\\\udcff'"),
        ("\\\udcff", "'\\\\\\xff'"),
        ("it's", '"it\'s"'),
    ],
)
def test_quoted_writes_an_undecoded_byte_as_text_output_does(text: str, shown: str) -> None:
    assert quoted(text) == shown
