"""Assert that links between repository documents resolve.

Documentation cross-references rot silently. A renamed file leaves a
link that still looks correct in the source and 404s for the reader, and
nothing in the build notices.

Two link styles are checked, because the documents use both. Relative
paths appear between documents in `docs/`. Absolute
`github.com/.../blob/main/...` URLs appear in the README and `llms.txt`,
which must render correctly on PyPI and when quoted out of context —
those resolve to a repository path just the same, and go stale just the
same.

Links to genuinely external sites are *not* checked. Doing so would make
the suite depend on the network and on other people's uptime, which
buys less than it costs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# Markdown inline links: [text](target). Reference-style links and bare
# autolinks are not used in these documents.
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Self-referential links written as absolute URLs. The README and
# llms.txt use these so they render correctly on PyPI and when quoted
# out of context, which means the plain relative-path check below cannot
# see them -- and a renamed file leaves them broken and unnoticed.
_README = _ROOT / "README.md"

_SELF_URL = re.compile(r"https://github\.com/varaprasadchilakanti/reveille/blob/main/([^)\s#]+)")

_DOCUMENTS = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "docs/ARCHITECTURE.md",
    "docs/USER_GUIDE.md",
    "docs/adr/README.md",
]


def _relative_targets(path: Path) -> list[str]:
    """Extract link targets that point inside the repository.

    Args:
        path: The Markdown file to scan.

    Returns:
        Link targets with any `#fragment` stripped, excluding external
        URLs and pure in-page anchors.
    """
    targets = []
    for raw in _LINK.findall(path.read_text(encoding="utf-8")):
        target = raw.split()[0].strip()
        if target.startswith(("http://", "https://", "mailto:", "#", "<")):
            continue
        targets.append(target.split("#")[0])
    return [t for t in targets if t]


@pytest.mark.unit
class TestDocumentationLinks:
    """Tests that in-repository documentation links point at real files."""

    @pytest.mark.parametrize("document", _DOCUMENTS)
    def test_document_exists(self, document: str) -> None:
        """Guard the guard: a renamed document must fail loudly here."""
        assert (_ROOT / document).is_file(), f"{document} is listed for checking but does not exist"

    @pytest.mark.parametrize("document", _DOCUMENTS)
    def test_relative_links_resolve(self, document: str) -> None:
        path = _ROOT / document
        broken = [
            target
            for target in _relative_targets(path)
            if not (path.parent / target).resolve().exists()
        ]
        assert not broken, f"{document} links to missing paths: {broken}"

    @pytest.mark.parametrize("document", [*_DOCUMENTS, "llms.txt"])
    def test_self_referential_urls_point_at_real_paths(self, document: str) -> None:
        """A `blob/main/...` URL naming a file this repository no longer has."""
        path = _ROOT / document
        targets = _SELF_URL.findall(path.read_text(encoding="utf-8"))
        broken = [t for t in targets if not (_ROOT / t).exists()]
        assert not broken, f"{document} links to repository paths that do not exist: {broken}"

    def test_llms_txt_is_well_formed(self) -> None:
        """`llms.txt` requires an H1; the blockquote summary is by convention.

        Both are what a consuming model reads first, so an empty or
        heading-less file is worse than no file at all.
        """
        lines = (_ROOT / "llms.txt").read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("# "), "llms.txt must open with an H1 naming the project"
        assert any(line.startswith("> ") for line in lines[:5]), (
            "llms.txt should carry a blockquote summary near the top"
        )

    def test_every_adr_is_listed_in_the_index(self) -> None:
        """An unlisted ADR is one nobody finds."""
        adr_dir = _ROOT / "docs" / "adr"
        on_disk = {p.name for p in adr_dir.glob("*.md")} - {"README.md"}
        listed = set(_relative_targets(adr_dir / "README.md"))
        assert on_disk, "no ADRs found -- the check below would be vacuous"
        assert on_disk == listed, f"index and directory disagree: {on_disk ^ listed}"


@pytest.mark.unit
class TestReadmeStructure:
    """The README's own table of contents must match its headings.

    Added after an edit truncated the file at `## Licence` and left the
    document with a duplicated `## Contributing`, a table of contents entry
    pointing at a heading that no longer existed, and no licence section at
    all. Every individual link still resolved, so nothing failed -- the
    document was internally broken in a way only its own structure revealed.
    """

    def test_no_heading_appears_twice(self) -> None:
        """A duplicated section is a sign an edit went wrong, not a choice."""
        headings = re.findall(r"^## (.+)$", _README.read_text(encoding="utf-8"), re.M)

        duplicates = sorted({h for h in headings if headings.count(h) > 1})
        assert not duplicates, f"duplicated README headings: {duplicates}"

    def test_contents_list_matches_the_headings(self) -> None:
        """Every anchor in the contents must name a heading, and vice versa."""
        text = _README.read_text(encoding="utf-8")
        listed = set(re.findall(r"^- \[([^\]]+)\]\(#", text, re.M))
        headings = set(re.findall(r"^## (.+)$", text, re.M)) - {"Contents"}

        assert listed == headings, (
            f"listed but absent: {sorted(listed - headings)}; "
            f"present but unlisted: {sorted(headings - listed)}"
        )
