# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""This repository's own `.mailmap`, checked with this repository's parser.

The file is a worked example the User Guide points readers at, so it has
to keep working. It is also the fix for a real reading of this project's
own report: one commit made through the GitHub web interface carried the
account's noreply address, so the contributors table listed three people
where there are two.

That mattered more than a spare row. The charts key on the display name,
and Plotly resolves a repeated label differently per trace type -- a bar
chart collapses the bars onto one category, a pie sums the slices -- so
the table said 201 and 1, the bar chart said 201, and the pie said 202.
Three views of one repository, three answers. Mapping the identities
makes all three agree at 202.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader, _Mailmap, _resolve_identity

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAILMAP = _REPO_ROOT / ".mailmap"

_CANONICAL_NAME = "Vara Prasad Chilakanti"
_CANONICAL_EMAIL = "varaprasadchilakanti@gmail.com"


def _address_of(identity: str) -> str:
    """Return the address from a `Name <address>` line, lowercased.

    Args:
        identity: One `git shortlog -sne` identity line.

    Returns:
        The address, or an empty string if the line carries none.
    """
    match = re.search(r"<([^<>]*)>\s*$", identity)
    return match.group(1).strip().lower() if match else ""


def _is_github_noreply(address: str) -> bool:
    """Whether an address is in GitHub's private-commit domain.

    Matched on the domain, not as a substring. A substring test for
    `noreply.github.com` also matches `noreply.github.com.example.net`,
    which is a different host entirely -- that is the unsoundness the
    original form was flagged for.

    The domain is `users.noreply.github.com` for both the legacy
    `username@` and the post-2017 `12345678+username@` forms. An earlier
    automated correction tested `endswith("@noreply.github.com")`, which
    no real GitHub address can satisfy: the `@` never lines up, because
    `users.` sits between. That silently retired this guard -- verified
    by deleting the `.mailmap` line it protects and watching the test
    still pass.

    Args:
        address: An email address, lowercased.

    Returns:
        True if the address is a GitHub noreply address.
    """
    _, _, domain = address.partition("@")
    return domain == "users.noreply.github.com"


@pytest.fixture(scope="module")
def mailmap() -> _Mailmap:
    """The repository's own `.mailmap`, read by the shipped parser."""
    assert _MAILMAP.is_file(), (
        "the repository's .mailmap is missing; the User Guide links to it as a worked example"
    )
    return GitReader(_REPO_ROOT)._read_mailmap()


@pytest.mark.unit
class TestTheRepositoryMailmapFoldsItsOwnAliases:
    """Each entry is asserted against the identity it exists to fold."""

    def test_it_parses_to_at_least_one_rule(self, mailmap: _Mailmap) -> None:
        assert mailmap.by_email or mailmap.by_name_and_email, (
            "the .mailmap parsed to no rules at all -- malformed lines are "
            "skipped silently, matching Git, so a typo shows up only here"
        )

    @pytest.mark.parametrize(
        ("name", "email"),
        [
            # The web-interface commit, in the prefixed form Git records.
            (
                "Vara Prasad Chilakanti",
                "140685918+varaprasadchilakanti@users.noreply.github.com",
            ),
            # The legacy unprefixed form of the same address.
            ("Vara Prasad Chilakanti", "varaprasadchilakanti@users.noreply.github.com"),
            # The pre-0.8.0 spelling of the display name.
            ("Varaprasad Chilakanti", _CANONICAL_EMAIL),
            # The canonical identity resolves to itself.
            (_CANONICAL_NAME, _CANONICAL_EMAIL),
        ],
    )
    def test_every_alias_resolves_to_the_canonical_identity(
        self, mailmap: _Mailmap, name: str, email: str
    ) -> None:
        resolved_name, resolved_email = _resolve_identity(name, email, mailmap)
        assert (resolved_name, resolved_email) == (_CANONICAL_NAME, _CANONICAL_EMAIL), (
            f"{name} <{email}> resolves to {resolved_name} <{resolved_email}>, "
            "so it would still be counted as a separate contributor"
        )

    def test_the_bot_is_left_alone(self, mailmap: _Mailmap) -> None:
        """A `.mailmap` states who is the same person. A bot is not one of us."""
        name, email = _resolve_identity(
            "dependabot[bot]",
            "49699333+dependabot[bot]@users.noreply.github.com",
            mailmap,
        )
        assert name == "dependabot[bot]"
        assert email == "dependabot[bot]@users.noreply.github.com", (
            "the numeric prefix is stripped by noreply normalisation, which "
            "needs no .mailmap entry; nothing else about the bot may change"
        )

    def test_an_unrelated_identity_is_untouched(self, mailmap: _Mailmap) -> None:
        """A mapping that catches strangers would silently merge real people."""
        name, email = _resolve_identity(
            "Someone Else",
            "someone@example.com",
            mailmap,
        )
        assert (name, email) == ("Someone Else", "someone@example.com")


@pytest.mark.unit
class TestGitItselfHonoursTheFile:
    """Reveille is not the only consumer, and it is the most forgiving one.

    Reveille strips the numeric prefix from a GitHub noreply address
    before looking it up, so its own resolution succeeds whether or not
    the prefixed form is mapped. Git does no such normalisation, and
    neither does GitHub's contributors graph: for them the prefixed
    address must be mapped literally or it stays a separate person.

    Removing that line therefore leaves every Reveille assertion above
    passing while `git shortlog` silently goes back to three identities.
    This is the test that notices.
    """

    def test_shortlog_sees_one_identity_per_person(self) -> None:
        if not (_REPO_ROOT / ".git").exists():
            pytest.skip("not a git checkout")

        completed = subprocess.run(
            ["git", "shortlog", "-sne", "--no-merges", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        identities = [
            line.strip().split("\t", 1)[1] for line in completed.stdout.splitlines() if "\t" in line
        ]

        assert f"{_CANONICAL_NAME} <{_CANONICAL_EMAIL}>" in identities, (
            f"git resolves the maintainer to {identities}, not to the "
            "canonical identity the .mailmap declares"
        )
        stray = [
            identity
            for identity in identities
            if _is_github_noreply(_address_of(identity)) and "dependabot" not in identity.lower()
        ]
        assert stray == [], (
            "git still counts a noreply address as its own contributor: "
            f"{stray}. Git does not strip the numeric prefix the way Reveille "
            "does, so that exact address has to be mapped literally."
        )
