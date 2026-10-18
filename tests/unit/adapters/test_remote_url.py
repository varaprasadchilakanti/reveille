"""Credentials never survive into the reported remote URL."""

from __future__ import annotations

import pytest

from reveille.adapters.git_reader import _without_credentials


@pytest.mark.unit
class TestWithoutCredentials:
    """Each case is an address Git accepts as a remote."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://user:SECRET@example.test/r.git", "https://example.test/r.git"),
            ("https://SECRET@example.test/r.git", "https://example.test/r.git"),
            ("https://example.test/r.git?private_token=SECRET", "https://example.test/r.git"),
            ("https://example.test:8443/r.git", "https://example.test:8443/r.git"),
            ("https://[::1]:8443/r.git", "https://[::1]:8443/r.git"),
            ("ssh://git@example.test:22/team/r.git", "ssh://git@example.test:22/team/r.git"),
            ("ssh://git:SECRET@example.test/r.git", "ssh://git@example.test/r.git"),
            ("file:///srv/git/r.git", "file:///srv/git/r.git"),
            ("git@example.test:team/r.git", "git@example.test:team/r.git"),
            # A transport prefix, `<transport>::<address>`, must not hide the
            # scheme from the credential stripping.
            ("https::https://SECRET@example.test/r.git", "https::https://example.test/r.git"),
            ("HTTPS::https://u:SECRET@example.test/r.git", "HTTPS::https://example.test/r.git"),
            ("remote-x::http://SECRET@example.test/r.git", "remote-x::http://example.test/r.git"),
            ("ext::ssh://git:SECRET@example.test/r.git", "ext::ssh://git@example.test/r.git"),
            # A raw `#` or `?` inside the credential must not end the stripping early.
            ("https://user:SE#CRET@example.test/r.git", "https://example.test/r.git"),
            ("https://SE?CRET@example.test", "https://example.test"),
            ("ssh://git:SE#CRET@example.test/r.git", "ssh://git@example.test/r.git"),
            ("https://example.test?private_token=SECRET", "https://example.test"),
            # scp-like, with a secret written into the user part.
            ("git:SECRET@example.test:team/r.git", "git@example.test:team/r.git"),
            ("git:SE@CRET@example.test:r.git", "git@example.test:r.git"),
            # Local paths are not addresses, whatever they contain.
            ("/srv/a:b@c/r.git", "/srv/a:b@c/r.git"),
            ("C:\\work\\a:b@c", "C:\\work\\a:b@c"),
        ],
    )
    def test_the_secret_goes_and_the_address_stays(self, raw: str, expected: str) -> None:
        assert _without_credentials(raw) == expected

    def test_a_malformed_address_does_not_raise(self) -> None:
        """`urlsplit` raised ValueError here, which crashed the run with exit 1."""
        assert _without_credentials("https://SECRET@[::1/r.git") == "https://[::1/r.git"
