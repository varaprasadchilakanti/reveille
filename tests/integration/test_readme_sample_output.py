# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The `summary` output the README shows is what the command prints on the sample repository.

The README holds it as text, so a change to `summary` would otherwise leave it stale unnoticed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    # About 760 Git calls; the README text needs checking once, on one platform.
    pytest.mark.skipif(sys.platform != "linux", reason="the README output is checked on Linux"),
]

_ROOT = Path(__file__).resolve().parents[2]
_COMMAND = "reveille summary --deterministic"


def _shown() -> str:
    readme = _ROOT.joinpath("README.md").read_text(encoding="utf-8")
    match = re.search(rf"`{_COMMAND}` prints:\n\n```text\n(.*?)```\n", readme, re.DOTALL)
    assert match, f"the README no longer shows the output of `{_COMMAND}`"
    return match.group(1)


def test_readme_shows_what_summary_prints(tmp_path: Path) -> None:
    # The directory name is the repository name the first line prints. The sample commits run
    # under the isolated Git configuration tests/conftest.py sets, so no signing or identity of
    # this machine reaches them.
    repo = tmp_path / "sample-service"
    subprocess.run(
        [sys.executable, str(_ROOT / "docs" / "images" / "make_sample_repository.py"), str(repo)],
        check=True,
        capture_output=True,
    )

    done = subprocess.run(
        [sys.executable, "-m", "reveille", *_COMMAND.split()[1:]],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout == _shown()
