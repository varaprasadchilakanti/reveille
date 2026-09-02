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
    """Every Python module in the package, `__init__.py` included.

    The exemption these once carried blinded three guarantees at once. A
    package's `__init__.py` executes at import, so `import socket` placed
    there would have been invisible to the offline check, to the dependency
    direction check, and to the filesystem-write check -- in the one file that
    is guaranteed to run.
    """
    return sorted(_SRC.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _package_of(path: Path) -> str:
    """The dotted package a module lives in, e.g. `reveille.adapters`."""
    return ".".join(["reveille", *path.relative_to(_SRC).parts[:-1]])


def _resolve_relative(path: Path, node: ast.ImportFrom) -> str:
    """Resolve `from ..services import x` to `reveille.services`.

    `node.level` is the number of leading dots: one means the current package,
    two means its parent, and so on.
    """
    parts = _package_of(path).split(".")
    drop = node.level - 1
    base = parts[: len(parts) - drop] if drop else parts
    return ".".join([*base, *(node.module.split(".") if node.module else [])])


def _imported_names(path: Path) -> set[str]:
    """Every module name this file imports directly, dotted form preserved.

    Relative imports are resolved to their absolute form. Skipping them --
    which this did, via `node.level == 0` -- left every dependency-direction
    guard blind to `from ..services import report`, which is ordinary Python
    and the most natural way to write an intra-package import. All four
    forbidden directions were reachable that way with the guards still green.
    """
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module if node.level == 0 else _resolve_relative(path, node)
            if not module:
                continue
            names.add(module)
            names.update(f"{module}.{a.name}" for a in node.names)
    return names


def _rel(path: Path) -> str:
    return str(path.relative_to(_SRC))


def _loop_values(loop: ast.For, name: str) -> set[str]:
    """String constants this `for` loop binds to `name`.

    Handles both `for field in ("since", "until")` and the tuple-unpacking
    form `for key, field in (("title", "title"), ("output", "output_path"))`,
    resolving which column `name` unpacks from.

    Scoped to one loop on purpose. Resolving by name across the whole module
    let a loop that merely *mentioned* a field satisfy the guard without
    assigning it -- the documentary-constant defect in a different costume.
    The caller only asks about loops whose body actually assigns `kwargs[name]`.
    """
    if not isinstance(loop.iter, ast.Tuple | ast.List | ast.Set):
        return set()

    if isinstance(loop.target, ast.Name) and loop.target.id == name:
        return {
            element.value
            for element in loop.iter.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }

    if not isinstance(loop.target, ast.Tuple):
        return set()

    values: set[str] = set()
    for index, element in enumerate(loop.target.elts):
        if not (isinstance(element, ast.Name) and element.id == name):
            continue
        for row in loop.iter.elts:
            if not isinstance(row, ast.Tuple | ast.List) or index >= len(row.elts):
                continue
            cell = row.elts[index]
            if isinstance(cell, ast.Constant) and isinstance(cell.value, str):
                values.add(cell.value)
    return values


def _subscript_assignment_keys(node: ast.AST) -> tuple[set[str], set[str]]:
    """Keys assigned via `x[...] = ...` under `node`: (literals, variable names)."""
    literals: set[str] = set()
    variables: set[str] = set()
    for inner in ast.walk(node):
        targets: list[ast.expr] = []
        if isinstance(inner, ast.Assign):
            targets = list(inner.targets)
        elif isinstance(inner, ast.AnnAssign | ast.AugAssign):
            targets = [inner.target]
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                literals.add(target.slice.value)
            elif isinstance(target.slice, ast.Name):
                variables.add(target.slice.id)
    return literals, variables


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
        request. This shows that no module names a network-capable import.

        Stated precisely, because the earlier wording -- "no code path could,
        because nothing capable of opening a socket is imported at all" -- was
        stronger than any static check can support. The package imports
        GitPython, which dispatches dynamically through `repo.git.<anything>`,
        and `git fetch` reaches the network. That path is closed by
        `TestFilesystemWrites._READ_ONLY_GIT`, which allowlists the three
        subcommands actually used, not by this test. The behavioural claim
        holds; it is held up by two guards rather than one.
        """
        offenders: list[str] = []
        for module in _modules():
            for name in _imported_names(module):
                root = name.split(".")[0]
                if name in _NETWORK_MODULES or (root in _NETWORK_MODULES and root != "urllib"):
                    offenders.append(f"{_rel(module)} imports {name}")

        assert not offenders, "network-capable imports in the package: " + "; ".join(offenders)

    def test_no_module_imports_dynamically_or_shells_out(self) -> None:
        """A static import check is only as good as the imports being static.

        `importlib.import_module("socket")` and `subprocess.run(["curl", ...])`
        both defeat the check above completely, and both passed it. Neither is
        used anywhere in the package, so forbidding them outright costs nothing
        and closes the two obvious ways round the guarantee.
        """
        escapes = frozenset({"importlib", "subprocess", "runpy", "ctypes", "multiprocessing"})
        offenders = [
            f"{_rel(module)} imports {name}"
            for module in _modules()
            for name in _imported_names(module)
            if name.split(".")[0] in escapes
        ]
        builtins_used = [
            f"{_rel(module)}:{node.lineno} __import__()"
            for module in _modules()
            for node in ast.walk(_tree(module))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
        ]

        assert not offenders + builtins_used, (
            "dynamic import or subprocess escape hatch: " + "; ".join(offenders + builtins_used)
        )


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

    # Attribute calls that create, modify or delete something on disk. The
    # original set was five `pathlib` methods, which missed `os.remove`,
    # `shutil.rmtree`, `os.makedirs` and `Path.rename` entirely.
    _WRITE_CALLS = frozenset(
        {
            "write_text",
            "write_bytes",
            "mkdir",
            "makedirs",
            "touch",
            "unlink",
            "removedirs",
            "rmdir",
            "rmtree",
            "rename",
            "renames",
            "copy2",
            "copyfile",
            "copytree",
            "symlink",
            "symlink_to",
            "hardlink_to",
            "chmod",
            "lchmod",
            "chown",
        }
    )

    # Names that also belong to ordinary types -- `str.replace`, `list.remove`,
    # `dict.copy`. Matching these on any receiver produced a false positive on
    # `capabilities.py`'s `str.replace`, so they count only when called on a
    # filesystem module. A guard that cries wolf gets weakened by whoever hits
    # it next, which is how a guard stops guarding.
    _AMBIGUOUS_WRITE_CALLS = frozenset(
        {"remove", "replace", "copy", "move", "link", "truncate", "writelines"}
    )
    _FS_MODULES = frozenset({"os", "shutil", "path"})

    # Git subcommands reached through `repo.git.<name>()`. An allowlist rather
    # than a blocklist, because this is the one call class that can genuinely
    # modify the repository being read -- `self._repo.git.gc()` mutates it, and
    # `git fetch` would also break the offline claim. GitPython dispatches
    # dynamically, so any attribute name is a valid command and a blocklist
    # would only ever cover the ones somebody thought of. Anything not listed
    # here fails the guard until a human adds it with a reason.
    _READ_ONLY_GIT = frozenset({"log", "rev_list", "rev_parse", "version"})

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
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                    if attr in self._WRITE_CALLS or (
                        attr in self._AMBIGUOUS_WRITE_CALLS and self._on_fs_module(node.func)
                    ):
                        offenders.append(f"{_rel(module)}:{node.lineno} .{attr}()")
                if isinstance(node, ast.Call):
                    opened = self._opened_for_writing(node)
                    if opened is not None:
                        offenders.append(f"{_rel(module)}:{node.lineno} open(..., {opened!r})")
                    git_command = self._mutating_git_command(node)
                    if git_command is not None:
                        offenders.append(f"{_rel(module)}:{node.lineno} .git.{git_command}()")

        assert not offenders, "filesystem writes outside the permitted modules: " + "; ".join(
            offenders
        )

    @classmethod
    def _on_fs_module(cls, func: ast.Attribute) -> bool:
        """True if the receiver is `os`, `shutil`, or `os.path`."""
        receiver = func.value
        if isinstance(receiver, ast.Name):
            return receiver.id in cls._FS_MODULES
        if isinstance(receiver, ast.Attribute):
            return receiver.attr in cls._FS_MODULES
        return False

    @staticmethod
    def _opened_for_writing(node: ast.Call) -> str | None:
        """Return the mode if this call opens a file for writing, else None.

        Covers both `open(path, "w")` and `path.open("w")`. Only the builtin
        was checked before, so `Path(...).open("w")` -- which is how
        `render_csv` writes, so not a hypothetical idiom -- went unseen.

        A non-constant mode is reported too. It cannot be shown to be
        read-only, and a guard that assumes the safe case when it cannot tell
        is the failure mode this whole module exists to avoid.
        """
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            positional = node.args[1:2]  # open(file, mode)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            positional = node.args[0:1]  # path.open(mode)
        else:
            return None

        mode_node = next(iter(positional), None)
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode_node = keyword.value

        if mode_node is None:
            return None  # defaults to "r"
        if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
            return "<not a literal>"
        return mode_node.value if any(f in mode_node.value for f in "wax+") else None

    @classmethod
    def _mutating_git_command(cls, node: ast.Call) -> str | None:
        """Return the subcommand if this is a `repo.git.<cmd>()` not known read-only."""
        func = node.func
        if not isinstance(func, ast.Attribute):
            return None
        parent = func.value
        if not (isinstance(parent, ast.Attribute) and parent.attr == "git"):
            return None
        return None if func.attr in cls._READ_ONLY_GIT else func.attr


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
            if name not in ("Exit", "SystemExit", "exit", "_exit"):
                continue
            # Positional as well as keyword. `typer.Exit.__init__` is
            # `(self, code: int = 0)`, so `typer.Exit(3)` sets exit code 3 --
            # and checking only `code=` meant the positional form, plus
            # `raise SystemExit(3)`, `sys.exit(3)` and `os._exit(3)`, all
            # widened a published contract with the guard still green.
            candidates = [*node.args[:1], *(k.value for k in node.keywords if k.arg == "code")]
            for candidate in candidates:
                if isinstance(candidate, ast.Constant) and isinstance(candidate.value, int):
                    offenders.append(
                        f"cli.py:{node.lineno} {name}() raises literal {candidate.value}"
                    )

        assert not offenders, (
            "literal exit codes: "
            + "; ".join(offenders)
            + ". Use an ExitCode member so the published contract stays visible."
        )

    def test_the_exit_code_enum_defines_exactly_the_published_codes(self) -> None:
        """A new member widens the contract as surely as a literal does.

        The literal check above passes for `ExitCode.WEIRD = 4`, because the
        call site looks like every other one. The three-way split is the
        contract, so the enum itself is what must be pinned.
        """
        from reveille.cli import ExitCode

        assert {member.value for member in ExitCode} == {0, 1, 2}


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
        # Only subscript *assignment targets* count -- `kwargs["field"] = ...`
        # and the loop form `for field in (...): kwargs[field] = ...`.
        #
        # Collecting every string constant in the file, which is what this did,
        # made the check a grep wearing an `ast` costume: a docstring, a
        # documentary constant, a key that was read and then dropped, or a key
        # wired to the wrong field all satisfied it. The middle two are the
        # realistic bug shapes, and it is why this guard could not catch the
        # `[report] format` defect -- it saw `kwargs["output_format"]` assigned
        # and passed, while the value was discarded downstream.
        tree = _tree(_CONFIG_SOURCE)
        assigned, _ = _subscript_assignment_keys(tree)

        # `for field in (...): kwargs[field] = ...` -- resolved only for loops
        # whose body genuinely performs that assignment.
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            _, variables = _subscript_assignment_keys(node)
            for variable in variables:
                assigned.update(_loop_values(node, variable))

        missing = sorted(set(ReportConfig.model_fields) - assigned - self._NOT_FROM_FILE)

        assert not missing, (
            f"ReportConfig fields with no reveille.toml key: {missing}. "
            "Either add a key to config.py's section parsers, or add the field "
            "to _NOT_FROM_FILE with a reason."
        )
