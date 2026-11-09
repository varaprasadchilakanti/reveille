# 0032 — GitPython stays as the Git runner

**Status:** Proposed (2026-11-09).

## Context

Reveille reads history through Git subprocesses with pinned settings (ADR 0019); it does not use
GitPython's object model. Removing the dependency was proposed, as one fewer runtime dependency
and one auditable read path.

GitPython does two jobs in `adapters/git_reader.py`, measured on Reveille 0.10.0 with GitPython 3.2.1:

- `Repo` gives three facts: `bare`, `git_dir` and `common_dir` (14 uses). Git's `rev-parse` gives
  the same three.
- Every Git command runs through GitPython's runner. `_TimedRepo` sets `GitCommandWrapperType` to
  `_TimedGit`, which adds the deadline; the no-output watchdog (`_Silence`) and `stop_running_git`
work through it.
  The module names `GitCommandError` 57 times.

## Decision

Keep GitPython as the Git runner, confined to `adapters/git_reader.py`. Revisit when any of these
holds:

- an advisory affects the declared floor (`gitpython = "^3.2.1"`) and no fixed release exists;
- GitPython has had no release for 12 months;
- a change to the runner is needed that GitPython blocks.

## Consequences

- Removing it means rewriting the runner, the deadline, the watchdog and stopping, and measuring
  each pinned setting (ADRs 0019 and 0024) again before and after. That is a larger change than
  dropping `Repo`.
- One runtime dependency stays, with its advisories. `tests/unit/test_dependency_floors.py` keeps
  the floor above releases with known advisories.

**Confirmation:** `test_layering.py::test_the_probe_can_actually_see_a_framework` fails if
`adapters/git_reader.py` stops importing GitPython, and
`test_architecture.py::test_each_framework_is_imported_by_its_owner_alone` if another module
imports it.
