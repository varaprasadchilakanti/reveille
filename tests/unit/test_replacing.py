# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`write_replacing` replaces only a regular file; a pipe or a device stays what it was.

Moving a new file over a name replaces whatever the name held: run as root,
`-o /dev/null` would have put a regular file where the device was.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from reveille.replacing import write_replacing


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_a_pipe_is_refused_and_left_in_place(tmp_path: Path) -> None:
    pipe = tmp_path / "out.html"
    os.mkfifo(pipe)

    with pytest.raises(OSError, match="not a regular file"):
        write_replacing(pipe, "x", encoding="utf-8")

    assert stat.S_ISFIFO(pipe.stat().st_mode)
    assert [p.name for p in tmp_path.iterdir()] == ["out.html"], "no temporary file left"


def test_a_regular_file_is_replaced(tmp_path: Path) -> None:
    target = tmp_path / "out.html"
    target.write_text("old", encoding="utf-8")

    write_replacing(target, "new", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "new"
