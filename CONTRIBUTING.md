# Contributing to Reveille

Thank you for considering a contribution. Please read this document
before opening a pull request.

## Reporting Issues

Use [GitHub Issues](https://github.com/varaprasadchilakanti/reveille/issues).
Include the output of `reveille --version`, your operating system,
your Python version, and a minimal reproduction case. If the issue
involves a specific repository, a sanitised `git log --oneline`
covering the relevant range is sufficient — do not include source code.

## Proposing Changes

Open an issue before beginning significant work. This prevents
duplicated effort and ensures alignment with the project's direction
before time is invested. Contributions that arrive without prior
discussion may be declined regardless of their quality.

## Development Environment

Requires Python 3.11 or later and `git`.

```bash
git clone git@github.com:varaprasadchilakanti/reveille.git
cd reveille
poetry install
poetry run pre-commit install
```

Verify the environment:

```bash
poetry run reveille --version
poetry run mypy src/
poetry run ruff check src/
poetry run pytest -n auto
```

## Supported Python versions

Reveille supports **every non-EOL CPython release at or above 3.11**. As of the 0.7.0
release that is **3.11, 3.12, 3.13, and 3.14**. Each is exercised by the CI matrix on
every pull request; each appears in the PyPI classifiers.

**The 3.11 floor is technical, not a preference.** `config.py` imports `tomllib` and
`git_reader.py` uses `datetime.UTC`, both added in 3.11. Lowering the floor means
vendoring a TOML parser and reworking timezone handling — not worth it while 3.10 is
weeks from end of life.

Three rules govern changes to this policy.

**1. A version is added to the classifiers only after CI proves it.** The classifier
advertises a tested configuration; it is evidence, not intent. Add the version to the
matrix, let CI run, and add the classifier in the same pull request once it is green.
If it fails, either fix the incompatibility or state the exclusion and its reason —
never quietly drop the version.

**2. Versions are dropped on their upstream EOL date**, not on convenience. This follows
the convention codified by SPEC 0 (successor to NEP 29) and used across the ecosystem.
Dropping a version is a breaking change for anyone still on it and belongs in a release
note.

**3. The `python` constraint carries no upper cap below 4.0, and must not gain one.**
`python = "^3.11"` resolves to `>=3.11,<4.0`. A tighter cap such as `<3.13` asserts that
Reveille *breaks* on 3.13, which is a much stronger claim than "untested" — and the
assertion is transitive: every project depending on Reveille inherits an unsatisfiable
constraint on an interpreter that most likely works, and this project inherits the
resulting reports. Not having tested a release is a reason to stay silent about it, not
to forbid it. If a genuine incompatibility is found, express it as a narrow, documented
exclusion rather than a blanket ceiling.

## Architecture

**Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before your first
change.** It describes the layering contract, the domain model, the
pipeline, and the invariants that tests exist to protect. Individual
decisions and their reasoning live in [docs/adr/](docs/adr/).

In short: dependencies point inward, and outer layers never appear in
inner ones.

- `src/reveille/domain/` — frozen dataclasses and the ranking engine.
  Performs no I/O and no rendering. It does import `RankingWeights` from
  `config.py`, which is a Pydantic model; that is a deliberate,
  documented exception rather than a leak.
- `src/reveille/adapters/` — `GitReader` (the only module that imports
  GitPython) and `Renderer` (the only module that imports Jinja2 and
  Plotly).
- `src/reveille/services/` — the `generate_report` orchestrator. Emits
  `ProgressEvent`; knows nothing about terminals.
- `src/reveille/cli.py` — the only module that imports Typer. Argument
  parsing, exit codes, and progress display. No business logic.

New behaviour belongs in the layer that owns its concern. Domain logic
that acquires an I/O or presentation import is a layering violation, and
`tests/unit/test_layering.py` will fail rather than leave it to review.

If a change makes a statement in `ARCHITECTURE.md` untrue, update the
document in the same pull request. An architecture document that
describes an intended design rather than the built one is worse than
none.

## Submitting Pull Requests

All pull requests must target the `main` branch. The CI pipeline runs
`ruff`, `mypy`, and `pytest` across every supported Python version — see
[Supported Python versions](#supported-python-versions) — plus a
packaging check and a version-consistency check. All must pass. A pull
request will not be merged if any check fails.

The output contract is non-negotiable and must be preserved in every
contribution: the generated file is always a single self-contained
`.html` file with no external dependencies, no CDN calls, no cookies,
and no tracking.

New public functions require Google-style docstrings. New behaviour
requires tests. The existing three-layer test pyramid (unit,
integration, end-to-end) is the structure to follow — add tests in
the layer appropriate to what is being exercised.

## Code Style

Ruff handles linting and import ordering. Mypy runs in strict mode.
Type annotations are required on every function signature. Early
returns are preferred over nested conditionals.

Run the full quality suite before pushing:

```bash
poetry run ruff check src tests
poetry run ruff format src tests
poetry run mypy src
poetry run pytest -n auto
```

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/)
specification. Scope is optional but encouraged.

```
feat(ranking): add recency decay weighting
fix(cli): use None sentinel for min_commits to preserve CLI precedence
docs(readme): add uv installation instructions
refactor(renderer): extract pie data aggregation into helper
test(e2e): verify help command exits zero and lists known subcommands
chore(release): bump version to 0.4.0
```

## Licence

By contributing to Reveille, you agree that your contributions will
be licensed under the [MIT Licence](LICENSE).
