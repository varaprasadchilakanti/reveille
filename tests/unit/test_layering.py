"""Executable form of the dependency rule in `docs/ARCHITECTURE.md`.

The layering contract is the project's main structural guarantee: the
domain is testable without a repository on disk, and swapping a data
source or an output format means writing one adapter rather than tracing
framework calls through the codebase. A contract that only exists in a
document erodes one convenient import at a time, and nothing fails.

Each check runs in a fresh interpreter, because `sys.modules` in the
test process is already polluted by everything the suite has imported.
A subprocess is the only way to observe what a module *actually* pulls
in, including transitively.

**The module list is discovered, not written down.** CLAUDE.md and
`docs/ARCHITECTURE.md` both say this file asserts the rule "by importing
each module". For a long time it imported two of eighteen, and the
sentence was false: `import plotly` added to `reveille.domain.summary`
left the layering checks green and the whole suite passing at 805 tests.
Discovery is what makes the sentence true and keeps it true -- a new
module inside `domain/` or `services/` is covered the day it is added,
and a new top-level module fails until somebody states which frameworks
it may load.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

# Frameworks that must never appear in the inner layers. Pydantic is
# deliberately absent: `domain/ranking.py` imports `RankingWeights` from
# `config.py` by design, which is documented in ARCHITECTURE.md under
# "One honest exception". What this list protects is the real rule --
# the domain performs no I/O and no presentation.
_IO_AND_PRESENTATION = frozenset({"git", "plotly", "jinja2", "typer", "click"})

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "reveille"

# Rules that apply to a package and everything beneath it, so a module
# added to that layer later is covered without editing this file.
_PACKAGE_RULES: dict[str, frozenset[str]] = {
    # The inner layer: no I/O, no presentation, at any depth.
    "reveille.domain": _IO_AND_PRESENTATION,
    # The service orchestrates domain and adapters, so it legitimately
    # loads GitPython, Plotly and Jinja transitively. What it must not
    # know about is the terminal: it emits ProgressEvent and nothing more.
    "reveille.services": frozenset({"typer", "click"}),
}

# Rules for individual modules, which win over the package rule. Each
# entry is a measured statement about that module, not an aspiration.
_MODULE_RULES: dict[str, frozenset[str]] = {
    "reveille": _IO_AND_PRESENTATION,
    "reveille.adapters": _IO_AND_PRESENTATION,
    "reveille.adapters.git_reader": frozenset({"plotly", "jinja2"}),
    "reveille.adapters.renderer": frozenset({"git"}),
    # `capabilities` describes the CLI but must not import it at module
    # scope, or every `reveille --version` pays for Typer.
    "reveille.capabilities": _IO_AND_PRESENTATION,
    "reveille.config": _IO_AND_PRESENTATION,
    "reveille.exceptions": _IO_AND_PRESENTATION,
    "reveille.init": _IO_AND_PRESENTATION,
    # The outermost layer. Typer and Click are its job.
    "reveille.cli": frozenset(),
}

_PROBE = """
import sys
import {module}
print(",".join(sorted({{m.split(".")[0] for m in sys.modules}})))
"""


def _discover_modules() -> list[str]:
    """Return every importable module under `src/reveille`, dotted.

    Returns:
        Dotted module paths, sorted. A package's `__init__.py` is
        reported as the package itself.
    """
    modules: list[str] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        parts = list(path.relative_to(_SOURCE_ROOT.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))
    return modules


_MODULES = _discover_modules()


def _forbidden_for(module: str) -> frozenset[str] | None:
    """Return the frameworks `module` must not load, or None if unruled.

    Args:
        module: Dotted module path.

    Returns:
        The forbidden set, or None when no rule covers the module --
        which is a failure, not a pass.
    """
    if module in _MODULE_RULES:
        return _MODULE_RULES[module]
    candidates = [
        name for name in _PACKAGE_RULES if module == name or module.startswith(f"{name}.")
    ]
    if not candidates:
        return None
    return _PACKAGE_RULES[max(candidates, key=len)]


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

    def test_every_module_is_covered_by_a_layer_rule(self) -> None:
        """A module nobody has ruled on is not a module nobody checked.

        This is the guard on the guard. Without it, adding
        `reveille/exporters.py` would silently sit outside every check
        below while the suite stayed green -- which is exactly how two
        of eighteen modules came to stand for "each module".
        """
        assert _MODULES, f"no modules discovered under {_SOURCE_ROOT}"
        unruled = sorted(name for name in _MODULES if _forbidden_for(name) is None)
        assert not unruled, (
            f"no layer rule covers {unruled}. State which frameworks each may "
            "load in _MODULE_RULES, or put it under a package that has a rule."
        )

    @pytest.mark.parametrize("module", _MODULES)
    def test_module_obeys_its_layer_rule(self, module: str) -> None:
        """Every module, in its own fresh interpreter."""
        forbidden = _forbidden_for(module)
        assert forbidden is not None, f"{module} has no layer rule"
        offenders = sorted(_top_level_imports(module) & forbidden)
        assert not offenders, f"{module} imports {offenders}, violating the dependency rule"

    def test_the_probe_can_actually_see_a_framework(self) -> None:
        """Positive controls. Without these, every check above proves nothing.

        A probe that silently reported an empty set would pass the whole
        class. The three modules that are *supposed* to load a framework
        must be observed loading it.
        """
        assert "git" in _top_level_imports("reveille.adapters.git_reader"), (
            "the probe found no GitPython in git_reader -- it is not observing imports"
        )
        renderer = _top_level_imports("reveille.adapters.renderer")
        assert {"plotly", "jinja2"} <= renderer, (
            f"the probe found only {sorted(renderer & {'plotly', 'jinja2'})} in renderer"
        )
        assert "typer" in _top_level_imports("reveille.cli"), (
            "the probe found no Typer in cli.py -- it is not observing imports"
        )

    def test_package_root_is_import_cheap(self) -> None:
        """`import reveille` must not drag in the whole framework stack.

        The root exposes `__version__` and installs a logging
        NullHandler. Anything that made it import Plotly would put a
        4.8 MB bundle read behind every `reveille --version`.
        """
        loaded = _top_level_imports("reveille")
        offenders = sorted(loaded & _IO_AND_PRESENTATION)
        assert not offenders, f"importing reveille pulls in {offenders}"
