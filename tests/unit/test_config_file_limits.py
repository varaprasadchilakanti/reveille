# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A configuration file is read only if it is a regular file a person could have written.

In-process, so the lines are measured; `test_config_file_that_blocks.py` runs
the same cases through the CLI in a child process, with a deadline.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

import pytest

from reveille.adapters.git_reader import RepositoryError, _checked
from reveille.config import ConfigurationError, load_config_from_toml

pytestmark = pytest.mark.unit


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_a_named_pipe_is_refused_without_waiting(tmp_path: Path) -> None:
    pipe = tmp_path / "reveille.toml"
    os.mkfifo(pipe)

    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_config_from_toml(pipe)


def test_a_file_larger_than_a_configuration_is_refused(tmp_path: Path) -> None:
    big = tmp_path / "reveille.toml"
    big.write_text(f'[report]\ntitle = "{"x" * (1 << 20)}"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="larger than"):
        load_config_from_toml(big)


def test_nesting_too_deep_for_the_parser_is_a_configuration_error(tmp_path: Path) -> None:
    deep = tmp_path / "reveille.toml"
    deep.write_text("x = " + "[" * 5000 + "]" * 5000 + "\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="nested too deeply"):
        load_config_from_toml(deep)


def test_a_window_in_the_file_is_read(tmp_path: Path) -> None:
    config = tmp_path / "reveille.toml"
    config.write_text('[report]\nsince = "2026-01-01"\nuntil = "2026-02-01"\n', encoding="utf-8")

    found = load_config_from_toml(config)

    assert (found["since"], found["until"]) == (
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
    )


def test_a_git_file_past_the_bound_is_refused_and_an_unbounded_one_read(tmp_path: Path) -> None:
    big = tmp_path / "config"
    with big.open("wb") as handle:
        handle.truncate(9 * 1024 * 1024)

    with pytest.raises(RepositoryError, match="larger than any configuration"):
        _checked(big)
    assert _checked(big, bounded=False)
