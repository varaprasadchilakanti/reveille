"""Assert that relative links between repository documents resolve.

Documentation cross-references rot silently. A renamed file leaves a
link that still looks correct in the source and 404s for the reader, and
nothing in the build notices. This branch added a document that links
into an ADR directory, and a CONTRIBUTING section that links into it, so
the failure mode is now real rather than hypothetical.

Only relative links are checked. External URLs would make the suite
depend on the network and on other people's uptime, which is a worse
trade than the coverage is worth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# Markdown inline links: [text](target). Reference-style links and bare
# autolinks are not used in these documents.
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

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

    def test_every_adr_is_listed_in_the_index(self) -> None:
        """An unlisted ADR is one nobody finds."""
        adr_dir = _ROOT / "docs" / "adr"
        on_disk = {p.name for p in adr_dir.glob("*.md")} - {"README.md"}
        listed = set(_relative_targets(adr_dir / "README.md"))
        assert on_disk, "no ADRs found -- the check below would be vacuous"
        assert on_disk == listed, f"index and directory disagree: {on_disk ^ listed}"
