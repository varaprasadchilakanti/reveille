# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Reveille reads a `.mailmap` line as Git does: `git check-mailmap` is the reference.

Each line is written to a repository's `.mailmap`, then probe identities are
mapped by Git and by Reveille's reader; the two must agree. Lines Git honours
and Reveille skipped would split or merge people differently from
`git shortlog`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader

pytestmark = pytest.mark.integration

_LINES = [
    "Ana Silva <ana@e.test>",
    "Ana Silva <ana@e.test> <old@e.test>",
    "<ana@e.test> <old@e.test>",
    "Ana Silva <ana@e.test> Old Name <old@e.test>",
    "Ana   Silva   <ana@e.test>    Old   Name    <old@e.test>",
    "Ana\t<ana@e.test>\t<old@e.test>",
    "Ana<ana@e.test>",
    "Ana <ana@e.test><old@e.test>",
    "<ana@e.test>",
    "Ana <>",
    "Ana <ana@e.test",
    "Ana <ana@e.test> trailing",
    "Ana <a <b@e.test>",
    "A>na <ana@e.test>",
    "Ana <ana@e.test> Old <old@e.test> x",
    "no address at all",
    "Ana  <ANA@E.TEST> <Old@E.Test>",
    "<ana@e.test> Old <old@e.test>",
    "Ana <ana@e.test> <old@e.test> <third@e.test>",
    "Ana <ana@e.test>Old <old@e.test>",
    "C# Team <team@e.test> <old@e.test>",
    "Proper <p@e.test> <old@e.test> trailing junk",
    "Solo Name <old@e.test> # a comment",
    "# Ana <ana@e.test> <old@e.test>",
    " # Ana <ana@e.test> <old@e.test>",
]

_PROBES = ["Zed <old@e.test>", "Old <old@e.test>", "Old Name <old@e.test>", "Zed <ana@e.test>"]


def _git_maps(repo: Path, probe: str) -> str:
    return subprocess.run(
        ["git", "check-mailmap", probe], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _reveille_maps(reader: GitReader, probe: str) -> str:
    name, _, rest = probe.partition(" <")
    email = rest.rstrip(">")
    entry = reader._read_mailmap().lookup(name, email)
    if entry is None:
        return probe
    mapped_name, mapped_email = entry
    return f"{mapped_name or name} <{mapped_email}>"


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("parity") / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    return path


@pytest.mark.parametrize("line", _LINES)
def test_each_line_maps_as_git_maps_it(repo: Path, line: str) -> None:
    (repo / ".mailmap").write_text(line + "\n", encoding="utf-8")
    reader = GitReader(repo)

    for probe in _PROBES:
        expected = _git_maps(repo, probe)
        actual = _reveille_maps(reader, probe)
        # Reveille keys and reports addresses in lower case.
        assert actual.lower() == expected.lower(), f"{line!r}: {probe} -> {actual}, Git: {expected}"


def test_a_later_line_updates_one_field_of_an_entry(repo: Path) -> None:
    """Git merges entries for the same address: the name from one line, the address from another."""
    (repo / ".mailmap").write_text(
        "Ana <old@e.test>\n<ana@e.test> <old@e.test>\n", encoding="utf-8"
    )
    reader = GitReader(repo)

    assert _reveille_maps(reader, "Zed <old@e.test>") == _git_maps(repo, "Zed <old@e.test>")


@pytest.mark.parametrize(
    "text",
    [
        "Proper Kim <p1@e.test> Kim <kim@e.test>\n<p2@e.test> Kim <kim@e.test>\n",
        "Ana <a1@e.test> <old@e.test>\n<a2@e.test> <old@e.test>\n",
        "<a2@e.test> <old@e.test>\nAna <old@e.test>\n",
    ],
)
def test_a_repeated_entry_replaces_or_merges_as_git_does(repo: Path, text: str) -> None:
    """A name-keyed entry is replaced whole; an address-keyed one is updated field by field."""
    (repo / ".mailmap").write_text(text, encoding="utf-8")
    reader = GitReader(repo)

    for probe in ("Kim <kim@e.test>", "Zed <old@e.test>"):
        expected = _git_maps(repo, probe)
        assert _reveille_maps(reader, probe).lower() == expected.lower(), (text, probe, expected)
