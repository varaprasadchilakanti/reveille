# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""File-level analysis: about paths, never about people."""

from __future__ import annotations

import pytest

from reveille.domain.files import (
    extension_breakdown,
    hotspots,
    is_generated,
)
from reveille.domain.models import FileStats


def _file(path: str, commits: int = 1, added: int = 0, deleted: int = 0) -> FileStats:
    return FileStats(path=path, commits=commits, lines_added=added, lines_deleted=deleted)


@pytest.mark.unit
class TestChurnIsAddedPlusDeleted:
    """A file that gains and loses a thousand lines has been worked on."""

    def test_lines_changed_is_not_net(self) -> None:
        assert _file("a.py", added=1000, deleted=1000).lines_changed == 2000

    def test_a_pure_deletion_ranks(self) -> None:
        ranked = hotspots([_file("a.py", added=0, deleted=500), _file("b.py", added=10)])
        assert ranked[0].path == "a.py"


@pytest.mark.unit
class TestGeneratedFilesAreExcludedByDefault:
    """A lock file tops every churn ranking and tells a reader nothing."""

    @pytest.mark.parametrize(
        "path",
        [
            "poetry.lock",
            "package-lock.json",
            "yarn.lock",
            "go.sum",
            "sub/dir/Cargo.lock",
            "Gemfile.lock",
        ],
    )
    def test_known_generated_files_are_recognised(self, path: str) -> None:
        assert is_generated(path)

    @pytest.mark.parametrize("path", ["src/lock.py", "locket.md", "a/b/main.go"])
    def test_ordinary_files_are_not(self, path: str) -> None:
        assert not is_generated(path)

    def test_they_are_dropped_from_hotspots(self) -> None:
        files = [_file("poetry.lock", added=99999), _file("src/a.py", added=10)]
        assert [f.path for f in hotspots(files)] == ["src/a.py"]

    def test_they_can_be_asked_for(self) -> None:
        files = [_file("poetry.lock", added=99999), _file("src/a.py", added=10)]
        ranked = hotspots(files, include_generated=True)
        assert ranked[0].path == "poetry.lock"

    def test_they_still_count_towards_the_type_breakdown(self) -> None:
        """Excluding them from a ranking is not the same as hiding the churn."""
        breakdown = dict(extension_breakdown([_file("poetry.lock", added=500)]))
        assert breakdown[".lock"] == 500


@pytest.mark.unit
class TestHotspotOrderingIsTotalAndReproducible:
    """Two runs over one repository must not disagree about the order."""

    def test_ties_break_deterministically(self) -> None:
        files = [_file("z.py", added=100), _file("a.py", added=100), _file("m.py", added=100)]
        assert [f.path for f in hotspots(files)] == ["a.py", "m.py", "z.py"]

    def test_commits_break_a_churn_tie_before_the_path_does(self) -> None:
        files = [_file("a.py", commits=1, added=100), _file("b.py", commits=9, added=100)]
        assert [f.path for f in hotspots(files)] == ["b.py", "a.py"]

    def test_the_limit_is_honoured(self) -> None:
        files = [_file(f"f{i}.py", added=i) for i in range(50)]
        assert len(hotspots(files, limit=5)) == 5

    def test_an_empty_history_yields_nothing(self) -> None:
        assert hotspots([]) == []


@pytest.mark.unit
class TestExtensionBreakdownPreservesTheTotal:
    """Pooling a tail must not lose churn."""

    def test_totals_survive_pooling(self) -> None:
        files = [_file(f"f{i}.e{i}", added=10) for i in range(20)]
        breakdown = extension_breakdown(files, limit=3)
        assert sum(value for _label, value in breakdown) == 200
        assert breakdown[-1][0] == "other"

    def test_no_pooled_row_when_nothing_is_pooled(self) -> None:
        files = [_file("a.py", added=1), _file("b.md", added=1)]
        assert [label for label, _ in extension_breakdown(files, limit=8)] == [".md", ".py"]

    def test_a_dotfile_has_no_extension(self) -> None:
        """`.gitignore` is a file called gitignore, not a gitignore-typed file."""
        assert dict(extension_breakdown([_file(".gitignore", added=5)])) == {"(none)": 5}

    def test_a_file_with_no_dot_has_no_extension(self) -> None:
        assert dict(extension_breakdown([_file("Makefile", added=5)])) == {"(none)": 5}

    def test_extensions_are_case_folded(self) -> None:
        files = [_file("a.PY", added=1), _file("b.py", added=1)]
        assert dict(extension_breakdown(files)) == {".py": 2}

    def test_ordering_is_by_churn_then_label(self) -> None:
        files = [_file("a.py", added=5), _file("b.md", added=5), _file("c.rs", added=9)]
        assert [label for label, _ in extension_breakdown(files)] == [".rs", ".md", ".py"]


@pytest.mark.unit
class TestItNamesNobody:
    """A file section in the default report must stay a file section."""

    def test_no_input_carries_an_identity(self) -> None:
        """`FileStats` has no author field at all, by construction."""
        assert not any(
            field in FileStats.__dataclass_fields__
            for field in ("author", "name", "email", "contributor")
        )
