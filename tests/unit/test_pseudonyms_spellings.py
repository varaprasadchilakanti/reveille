# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`--hide-emails` hides an address however its at sign is written.

A pattern cannot know every spelling, so these are the ones a person or a tool
writes: the fullwidth and small forms a phone keyboard gives, `%40` from a URL,
and spaces around the sign. Each errs towards hiding more.
"""

from __future__ import annotations

import pytest

from reveille.domain.pseudonyms import _hidden_in_path, _hidden_remote, _Tokens

_FULLWIDTH, _SMALL = chr(0xFF20), chr(0xFE6B)
_SPELLINGS = [
    "jane@corp.test",
    f"jane{_FULLWIDTH}corp.test",
    f"jane{_SMALL}corp.test",
    "jane%40corp.test",
]


@pytest.mark.parametrize("address", _SPELLINGS)
def test_a_branch_named_after_an_address_loses_it(address: str) -> None:
    hidden = _hidden_in_path(f"user/{address}/fix")

    assert hidden == "user/(address hidden)/fix"


@pytest.mark.parametrize("address", [*_SPELLINGS, "jane @corp.test", "jane @ corp.test"])
def test_a_name_holding_an_address_loses_it(address: str) -> None:
    assert _Tokens().name(f"Jane {address}") == "Jane (address hidden)"


@pytest.mark.parametrize(
    "remote",
    [
        "https://git.corp.test/jane%40corp.test/r.git",
        f"https://git.corp.test/jane{_FULLWIDTH}corp.test/r.git",
        "\\\\fileserver\\home\\jane\\r.git",
        "//fileserver/home/jane/r.git",
        "ext::ssh -l jane git.corp.test %S r.git",
    ],
)
def test_a_remote_keeps_no_login_address_or_home_directory(remote: str) -> None:
    hidden = _hidden_remote(remote)

    assert "jane" not in hidden, hidden


def test_an_ordinary_remote_keeps_its_host_and_path() -> None:
    assert _hidden_remote("https://git.corp.test/team/r.git") == "https://git.corp.test/team/r.git"
    assert _hidden_remote("jane@git.corp.test:team/r.git") == "git.corp.test:team/r.git"
