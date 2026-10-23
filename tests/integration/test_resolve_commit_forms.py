# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Every revision form Git reads names its commit, `:/<text>` included.

The name was peeled as `<name>^{commit}`; after `:/`, Git searches messages
for the rest, so `^{commit}` was searched for and `--from ':/text'` refused.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader
from reveille.exceptions import RepositoryError

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("forms") / "r"
    _git(path.parent, "init", "-q", "-b", "main", str(path))
    for message in ("start here", "second", "third"):
        _git(path, "commit", "-q", "--allow-empty", "-m", message)
    _git(path, "tag", "-a", "-m", "annotated", "v1", "HEAD~1")
    _git(path, "update-ref", "refs/tags/tree", _git(path, "rev-parse", "HEAD^{tree}"))
    return path


@pytest.mark.parametrize(
    ("form", "names"),
    [(":/start", "HEAD~2"), (":/^second", "HEAD~1"), ("v1", "HEAD~1"), ("HEAD~2", "HEAD~2")],
)
def test_a_form_git_reads_names_its_commit(repo: Path, form: str, names: str) -> None:
    assert GitReader(repo).resolve_commit(form) == _git(repo, "rev-parse", names)


@pytest.mark.parametrize("form", [":/no such message", "tree", "nope"])
def test_a_form_naming_no_commit_is_refused(repo: Path, form: str) -> None:
    with pytest.raises(RepositoryError, match="does not name a commit"):
        GitReader(repo).resolve_commit(form)
