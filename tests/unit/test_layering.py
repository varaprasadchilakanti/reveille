"""Executable form of the dependency rule in `docs/ARCHITECTURE.md`.

The layering contract is the project's main structural guarantee: the
domain is testable without a repository on disk, and swapping a data
source or an output format means writing one adapter rather than tracing
framework calls through the codebase. A contract that only exists in a
document erodes one convenient import at a time, and nothing fails.

Each check runs in a fresh interpreter, because `sys.modules` in the
test process is already polluted by everything the suite has imported.
A subprocess is the only way to observe what a module *actually* pulls
in.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# Frameworks that must never appear in the inner layers. Pydantic is
# deliberately absent: `domain/ranking.py` imports `RankingWeights` from
# `config.py` by design, which is documented in ARCHITECTURE.md under
# "One honest exception". What this list protects is the real rule --
# the domain performs no I/O and no presentation.
_IO_AND_PRESENTATION = ("git", "plotly", "jinja2", "typer", "click")

_PROBE = """
import sys
import {module}
print(",".join(sorted({{m.split(".")[0] for m in sys.modules}})))
"""


def _top_level_imports(module: str) -> set[str]:
    """Import a module in a clean interpreter and report what it loaded.

    Args:
        module: Dotted module path to import.

    Returns:
        The set of top-level package names present in `sys.modules`
        afterwards.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(module=module)],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.strip().split(","))


@pytest.mark.unit
class TestDependencyRule:
    """Tests that inner layers do not import outer-layer frameworks."""

    @pytest.mark.parametrize("module", ["reveille.domain.models", "reveille.domain.ranking"])
    def test_domain_imports_no_io_or_presentation_framework(self, module: str) -> None:
        loaded = _top_level_imports(module)
        offenders = sorted(loaded & set(_IO_AND_PRESENTATION))
        assert not offenders, f"{module} imports {offenders}, violating the dependency rule"

    def test_services_does_not_import_the_cli_framework(self) -> None:
        """The service emits ProgressEvent; it must not know about terminals."""
        loaded = _top_level_imports("reveille.services.report")
        assert "typer" not in loaded, (
            "services/report.py imports Typer; progress display is the CLI's job"
        )

    def test_gitpython_is_confined_to_its_adapter(self) -> None:
        assert "git" not in _top_level_imports("reveille.adapters.renderer")
        assert "git" in _top_level_imports("reveille.adapters.git_reader"), (
            "the probe found no GitPython in git_reader -- the check above proves nothing"
        )

    def test_plotly_and_jinja_are_confined_to_their_adapter(self) -> None:
        loaded = _top_level_imports("reveille.adapters.git_reader")
        offenders = sorted(loaded & {"plotly", "jinja2"})
        assert not offenders, f"git_reader.py imports {offenders}; rendering belongs to renderer.py"

    def test_package_root_is_import_cheap(self) -> None:
        """`import reveille` must not drag in the whole framework stack.

        The root exposes `__version__` and installs a logging
        NullHandler. Anything that made it import Plotly would put a
        ~3.5 MB bundle read behind every `reveille --version`.
        """
        loaded = _top_level_imports("reveille")
        offenders = sorted(loaded & set(_IO_AND_PRESENTATION))
        assert not offenders, f"importing reveille pulls in {offenders}"
