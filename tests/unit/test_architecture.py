"""Architectural fitness functions.

An architectural fitness function is a test whose subject is a *structural
property* of the system rather than a behaviour: the build fails when the shape
stops holding, not when a feature breaks. The term is from Ford, Parsons and
Kua, *Building Evolutionary Architectures* (2017), and `docs/ARCHITECTURE.md`
records it as the lineage for the checks in this repository.

The tests here complement rather than duplicate the ones already in place.
`test_layering.py` asserts the dependency rule by importing each module in a
subprocess and inspecting `sys.modules`, which catches a framework arriving
through any path including a transitive one. These assert properties that a
runtime probe cannot see: the *direction* of first-party imports, what a module
is permitted to do, and whether two surfaces that must stay in step have.

Each is written against the source with `ast` rather than with a text search.
That matters more than it sounds: a structural check built on `grep` matches
comments, docstrings and strings, so it can pass while the property it names is
false — which is exactly the failure mode these exist to prevent, and one this
project has shipped before.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import reveille
from reveille.config import ReportConfig

_SRC = Path(reveille.__file__).parent
_CONFIG_SOURCE = _SRC / "config.py"


def _modules() -> list[Path]:
    """Every Python module in the package."""
    return sorted(p for p in _SRC.rglob("*.py") if p.name != "__init__.py")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(path: Path) -> set[str]:
    """Every module name this file imports directly, dotted form preserved."""
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _rel(path: Path) -> str:
    return str(path.relative_to(_SRC))


# Modules that can open a socket. `urllib.parse` is deliberately absent: it
# parses strings and reaches nothing.
_NETWORK_MODULES = frozenset(
    {
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "webbrowser",
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "urllib.error",
        "http.client",
        "xmlrpc.client",
    }
)


@pytest.mark.unit
class TestOfflineGuarantee:
    """Reveille makes no network call. That is product behaviour, not a detail."""

    def test_no_module_imports_a_network_capability(self) -> None:
        """The guarantee is asserted at the source, not only at runtime.

        An end-to-end test can only show that a *particular* run made no
        request. This shows that no code path could, because nothing capable of
        opening a socket is imported at all. The two are different claims and
        the project makes the stronger one.
        """
        offenders: list[str] = []
        for module in _modules():
            for name in _imported_names(module):
                root = name.split(".")[0]
                if name in _NETWORK_MODULES or (root in _NETWORK_MODULES and root != "urllib"):
                    offenders.append(f"{_rel(module)} imports {name}")

        assert not offenders, "network-capable imports in the package: " + "; ".join(offenders)


@pytest.mark.unit
class TestDependencyDirection:
    """`CLI → Service → Domain ← Adapters`. Arrows point one way."""

    def test_domain_does_not_import_outward(self) -> None:
        """The domain is the centre; nothing outside it may be pulled in.

        `domain/ranking.py` imports `RankingWeights` from `config.py`, which is
        the one documented exception and is not an outward layer -- see
        docs/ARCHITECTURE.md. Everything else is forbidden.
        """
        forbidden = ("reveille.adapters", "reveille.services", "reveille.cli")
        offenders = [
            f"{_rel(m)} imports {name}"
            for m in _modules()
            if m.parent.name == "domain"
            for name in _imported_names(m)
            if name.startswith(forbidden)
        ]

        assert not offenders, "domain reaches outward: " + "; ".join(offenders)

    def test_services_do_not_import_the_cli(self) -> None:
        """The service holds no opinion about output devices.

        It reports progress by emitting events to a callback; whether those
        become a spinner, log lines or nothing is the CLI's decision.
        """
        offenders = [
            f"{_rel(m)} imports {name}"
            for m in _modules()
            if m.parent.name == "services"
            for name in _imported_names(m)
            if name.startswith("reveille.cli")
        ]

        assert not offenders, "service layer reaches the CLI: " + "; ".join(offenders)

    def test_adapters_do_not_import_each_other(self) -> None:
        """Two adapters coupled together are one adapter with two names.

        The git reader and the renderer sit on opposite sides of the domain and
        must be replaceable independently.
        """
        offenders: list[str] = []
        for module in _modules():
            if module.parent.name != "adapters":
                continue
            for name in _imported_names(module):
                if name.startswith("reveille.adapters") and module.stem not in name:
                    offenders.append(f"{_rel(module)} imports {name}")

        assert not offenders, "adapters are coupled: " + "; ".join(offenders)


@pytest.mark.unit
class TestFilesystemWrites:
    """Reveille never modifies the repository it reads."""

    # The only modules that may write: the renderer produces the report, and
    # `init` scaffolds a config file the user explicitly asked for.
    _MAY_WRITE = frozenset({"adapters/renderer.py", "init.py"})
    _WRITE_CALLS = frozenset({"write_text", "write_bytes", "mkdir", "touch", "unlink"})

    def test_only_designated_modules_write_to_disk(self) -> None:
        """A write from the reader or the domain would break the read-only claim.

        This is the structural form of a guarantee `SECURITY.md` makes in prose
        and `reveille capabilities` states to any program that asks.
        """
        offenders: list[str] = []
        for module in _modules():
            if _rel(module) in self._MAY_WRITE:
                continue
            for node in ast.walk(_tree(module)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self._WRITE_CALLS
                ):
                    offenders.append(f"{_rel(module)}:{node.lineno} .{node.func.attr}()")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "open"
                ):
                    mode = next(
                        (
                            a.value
                            for a in node.args[1:2]
                            if isinstance(a, ast.Constant) and isinstance(a.value, str)
                        ),
                        "r",
                    )
                    if any(flag in mode for flag in ("w", "a", "x", "+")):
                        offenders.append(f"{_rel(module)}:{node.lineno} open(..., {mode!r})")

        assert not offenders, "filesystem writes outside the permitted modules: " + "; ".join(
            offenders
        )


@pytest.mark.unit
class TestExitCodeContract:
    """Exit codes are published; only the three defined ones may be used."""

    def test_no_literal_exit_code_is_raised(self) -> None:
        """A bare `typer.Exit(code=3)` would silently widen a public contract.

        The three-way split -- affirmative, negative answer, could not run --
        is what a CI job branches on. A fourth code appearing without a
        decision behind it is a breaking change nobody noticed making.
        """
        cli = _SRC / "cli.py"
        offenders: list[str] = []
        for node in ast.walk(_tree(cli)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "Exit":
                continue
            for keyword in node.keywords:
                if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                    offenders.append(f"cli.py:{node.lineno} raises literal {keyword.value.value}")

        assert not offenders, "literal exit codes: " + "; ".join(offenders)


@pytest.mark.unit
class TestConfigurationSurface:
    """`reveille.toml` is the single configuration surface, so it must be whole."""

    # Set from the invocation rather than from a file: the repository path is
    # positional context, and the output path has its own `output` key handled
    # separately by the report-section parser.
    _NOT_FROM_FILE = frozenset({"repo_path"})

    def test_every_config_field_is_reachable_from_toml(self) -> None:
        """A field the file cannot set is a flag pretending to be configuration.

        This caught `deterministic` shipping as a CLI flag with no TOML key: the
        field existed on the model, the docs described `reveille.toml` as the
        single configuration surface, and the parser never read it. Nothing else
        in the suite would have noticed, because every individual piece worked.
        """
        assigned: set[str] = set()
        for node in ast.walk(_tree(_CONFIG_SOURCE)):
            # kwargs["field"] = ...
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                assigned.add(node.slice.value)
            # for field in ("since", "until"): kwargs[field] = ...
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assigned.add(node.value)

        missing = sorted(set(ReportConfig.model_fields) - assigned - self._NOT_FROM_FILE)

        assert not missing, (
            f"ReportConfig fields with no reveille.toml key: {missing}. "
            "Either add a key to config.py's section parsers, or add the field "
            "to _NOT_FROM_FILE with a reason."
        )
