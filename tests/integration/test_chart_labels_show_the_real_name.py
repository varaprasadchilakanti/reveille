# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A chart shows a name as it is: no markup, no entity, and no two files as one.

Plotly reads tags in a label, then decodes `&...;` entities in the text between
them. A label that lost its tags merged `app<x>.py` into `app.py`, and an entity
such as `&#8238;` was decoded into the direction control the label had escaped.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

# The entities the pinned plotly.js decodes, in one pass, between tags.
_ENTITY = re.compile(r"&(#\d+|#x[\da-fA-F]+|[a-z]+);", re.IGNORECASE)
_NAMED = {"mu": "\u03bc", "amp": "&", "lt": "<", "gt": ">", "nbsp": "\xa0", "times": "\xd7"}


def _as_plotly_shows(label: str) -> str:
    def decode(match: re.Match[str]) -> str:
        body = match.group(1)
        if body.startswith("#"):
            number = int(body[2:], 16) if body[1] in "xX" else int(body[1:])
            return chr(number) if number <= 0x10FFFF else match.group(0)
        return _NAMED.get(body, match.group(0))

    assert not re.search(r"<[^>]*>", label), f"Plotly would read a tag in {label!r}"
    return _ENTITY.sub(decode, label)


def _report(tmp_path: Path, files: dict[str, int], author: str = "A") -> str:
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name, lines in files.items():
        (repo / name).write_text("x\n" * lines, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", f"user.name={author}", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
    )
    out = repo / "report.html"
    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "--output", str(out)])
    assert result.exit_code == ExitCode.SUCCESS, result.output
    return out.read_text(encoding="utf-8")


def _spec(page: str, chart: str) -> dict:
    found = re.search(rf'id="spec-{chart}">\s*(.*?)\s*</script>', page, re.S)
    assert found, f"positive control: the {chart} chart is in the page"
    return json.loads(found.group(1))


def _hotspot_labels(page: str) -> list[str]:
    trace = _spec(page, "hotspots")["data"][0]
    return [_as_plotly_shows(str(label)) for label in trace["y"]]


def test_an_entity_in_a_path_is_shown_as_typed_not_decoded(tmp_path: Path) -> None:
    page = _report(tmp_path, {"invoice&#8238;fdp.exe": 30, "a&amp;b.txt": 20})

    shown = _hotspot_labels(page)

    assert "invoice&#8238;fdp.exe" in shown and "a&amp;b.txt" in shown, shown
    assert not any("\u202e" in label for label in shown), shown


def test_an_entity_in_an_author_name_is_not_decoded(tmp_path: Path) -> None:
    page = _report(tmp_path, {"a.txt": 3}, author="Mal&#x202E;yrolam")

    names = [_as_plotly_shows(str(n)) for n in _spec(page, "contributor_lines")["data"][0]["x"]]

    assert names == ["Mal&#x202E;yrolam"], names


def test_two_paths_that_differ_by_markup_stay_two(tmp_path: Path) -> None:
    page = _report(tmp_path, {"app.py": 5, "app<x>.py": 400, "<z>": 9})

    shown = _hotspot_labels(page)

    assert sorted(shown) == ["<z>", "app.py", "app<x>.py"], shown
    assert '<th scope="row">app&lt;x&gt;.py</th>' in page, "the table names the real file"
