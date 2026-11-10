# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A path Git prints quoted decodes to the name of the file Git listed."""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reveille.adapters.git_reader import _unquote_path

pytestmark = [
    pytest.mark.integration,
    # Linux keeps a file name's bytes as given; macOS normalises and Windows refuses some.
    pytest.mark.skipif(
        sys.platform != "linux", reason="file names are kept byte for byte on Linux"
    ),
]

_NAME = st.text(
    st.characters(exclude_characters="/\0", exclude_categories=("Cs",)), min_size=1
).filter(lambda n: n not in (".", "..", ".git") and len(n.encode()) <= 200)
_COUNTER = itertools.count()


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("quoted")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


# Each example writes a file and runs Git once, so the budget is small.
@settings(max_examples=50, deadline=None)
@given(name=_NAME)
def test_a_listed_path_decodes_to_the_file_name(repo: Path, name: str) -> None:
    folder = f"d{next(_COUNTER)}"
    (repo / folder).mkdir()
    (repo / folder / name).write_bytes(b"")

    listed = subprocess.run(
        ["git", "-c", "core.quotePath=true", "ls-files", "--others", "--", folder],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", "surrogateescape")

    assert _unquote_path(listed.removesuffix("\n")) == f"{folder}/{name}"
