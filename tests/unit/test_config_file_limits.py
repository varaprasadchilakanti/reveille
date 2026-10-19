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


def test_a_byte_order_mark_is_read_as_utf8(tmp_path: Path) -> None:
    """Some editors start a UTF-8 file with one; TOML's parser called it an invalid statement."""
    config = tmp_path / "reveille.toml"
    config.write_bytes(b'\xef\xbb\xbf[report]\ntitle = "x"\n')

    assert load_config_from_toml(config)["title"] == "x"


@pytest.mark.parametrize("value", ['"0.30"', "true"])
def test_a_weight_that_is_not_a_number_is_refused(tmp_path: Path, value: str) -> None:
    """`float("0.30")` and `float(True)` both succeeded, so `commits = true` weighed 1.0."""
    config = tmp_path / "reveille.toml"
    config.write_text(
        f"[ranking]\nweights = {{ commits = {value}, lines = 0, consistency = 0, recency = 0 }}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="weights commits must be a number"):
        load_config_from_toml(config)


@pytest.mark.parametrize(
    ("weights", "says"),
    [
        (
            "commits = 1.5, lines = 0.25, consistency = 0.25, recency = 0.20",
            "commits: Input should",
        ),
        ("commits = 0.9, lines = 0.25, consistency = 0.25, recency = 0.20", "must sum to 1.0, got"),
    ],
)
def test_a_weight_error_is_one_plain_sentence(tmp_path: Path, weights: str, says: str) -> None:
    config = tmp_path / "reveille.toml"
    config.write_text(f"[ranking]\nweights = {{ {weights} }}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as raised:
        load_config_from_toml(config)

    message = str(raised.value)
    assert says in message, message
    assert "pydantic" not in message and "input_value" not in message and "\n" not in message
