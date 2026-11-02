# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The workflows stay in the repository's source archives.

`.gitattributes` marked `.github/` `export-ignore`, so an archive of the
repository held no workflows, and OpenSSF Scorecard reported "no workflows
found" for the checks that read them.
"""

from __future__ import annotations

import subprocess
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]


def _archived() -> set[str]:
    """Top-level names in `git archive`, under the working tree's `.gitattributes`."""
    archive = subprocess.run(
        ["git", "archive", "--worktree-attributes", "--format=tar", "HEAD"],
        cwd=_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=BytesIO(archive)) as tar:
        return {name.split("/", 1)[0] for name in tar.getnames()}


def test_archives_keep_the_workflows() -> None:
    names = _archived()

    assert ".github" in names
    assert "tests" not in names, "positive control: export-ignore is applied"
