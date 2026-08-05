"""Unit tests for reveille.exceptions.

Two contracts are under test. The hierarchy contract: every Reveille
failure is catchable as a single base class, which is what the public
documentation tells consumers to rely on. The compatibility contract:
the pre-v0.7.0 misspelling still resolves, so upgrading does not break
`except RevelleError` in code written against an earlier release.
"""

from __future__ import annotations

import pytest

import reveille.exceptions as exc_module
from reveille.exceptions import (
    ConfigurationError,
    EmptyRepositoryError,
    OutputPathError,
    RenderError,
    RepositoryError,
    ReveilleError,
)

_SUBCLASSES = [
    RepositoryError,
    EmptyRepositoryError,
    ConfigurationError,
    RenderError,
    OutputPathError,
]


@pytest.mark.unit
class TestExceptionHierarchy:
    """Tests for the documented inheritance contract."""

    @pytest.mark.parametrize("subclass", _SUBCLASSES)
    def test_every_error_is_a_reveille_error(self, subclass: type[Exception]) -> None:
        """The single-catch guarantee the public docs make."""
        assert issubclass(subclass, ReveilleError)

    def test_empty_repository_error_is_a_repository_error(self) -> None:
        assert issubclass(EmptyRepositoryError, RepositoryError)

    def test_output_path_error_is_a_render_error(self) -> None:
        assert issubclass(OutputPathError, RenderError)

    @pytest.mark.parametrize("subclass", _SUBCLASSES)
    def test_catching_the_base_class_catches_every_subclass(
        self, subclass: type[Exception]
    ) -> None:
        with pytest.raises(ReveilleError):
            raise subclass("failure")

    def test_reveille_error_is_an_exception(self) -> None:
        assert issubclass(ReveilleError, Exception)


@pytest.mark.unit
class TestDeprecatedAlias:
    """Tests for the retained pre-v0.7.0 spelling, `RevelleError`."""

    def test_alias_resolves_to_the_corrected_class(self) -> None:
        """Identity, not merely a compatible subclass.

        Consumers may compare with `is`, and a distinct class would also
        break `except RevelleError` for errors raised internally as
        ReveilleError subclasses.
        """
        with pytest.warns(DeprecationWarning):
            assert exc_module.RevelleError is ReveilleError

    def test_alias_emits_a_deprecation_warning_naming_its_replacement(self) -> None:
        with pytest.warns(DeprecationWarning, match="Use ReveilleError instead"):
            _ = exc_module.RevelleError

    def test_alias_warning_states_the_removal_version(self) -> None:
        """A deprecation without a removal version is not actionable."""
        with pytest.warns(DeprecationWarning, match="v1.0.0"):
            _ = exc_module.RevelleError

    def test_catching_the_alias_still_catches_reveille_failures(self) -> None:
        """The behaviour the alias exists to preserve."""
        with pytest.warns(DeprecationWarning):
            legacy_base = exc_module.RevelleError
        with pytest.raises(legacy_base):
            raise ConfigurationError("failure")

    def test_unknown_attribute_still_raises_attribute_error(self) -> None:
        """The module __getattr__ must not swallow genuine typos."""
        with pytest.raises(AttributeError, match="no attribute 'NoSuchError'"):
            _ = exc_module.NoSuchError  # type: ignore[attr-defined]

    def test_alias_is_absent_from_the_public_export_list(self) -> None:
        """`__all__` advertises the supported surface; the alias is not it."""
        assert "ReveilleError" in exc_module.__all__
        assert "RevelleError" not in exc_module.__all__
