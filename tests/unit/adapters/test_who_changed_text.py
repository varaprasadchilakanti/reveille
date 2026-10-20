# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`who-changed` names the most recent authors only when that is not every author.

The recent list is at most five of the authors. With five or fewer authors it is the
authors list again, printed on the line above it.
"""

from __future__ import annotations

import datetime
import json

import pytest

from reveille.adapters.renderer import Renderer
from reveille.domain.areas import PathAnswer

pytestmark = pytest.mark.unit

_WINDOW = (datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))


def _answer(authors: int, recent: int) -> PathAnswer:
    people = tuple((f"Person {i}", f"p{i}@e.test") for i in range(authors))
    return PathAnswer(
        path="a.txt",
        commits=authors,
        last_changed=datetime.date(2026, 6, 1),
        authors=people,
        recently_active=people[:recent],
        automated=(),
        co_authored_commits=0,
        co_authors=(),
    )


def _text(answer: PathAnswer) -> str:
    return Renderer.who_changed_text(answer, _WINDOW, "text", 20)


def test_with_every_author_recent_the_line_is_left_out() -> None:
    text = _text(_answer(authors=3, recent=3))

    assert "Changed it most recently" not in text
    assert "Authors: Person 0, Person 1, Person 2." in text


def test_with_more_authors_than_recent_the_line_is_printed() -> None:
    text = _text(_answer(authors=7, recent=5))

    assert "Changed it most recently: Person 0, Person 1, Person 2, Person 3, Person 4." in text


def test_json_carries_the_recent_list_either_way() -> None:
    document = json.loads(Renderer.who_changed_text(_answer(3, 3), _WINDOW, "json", 20))

    assert len(document["recently_active"]) == 3
