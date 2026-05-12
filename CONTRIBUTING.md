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

## Architecture

Reveille follows Clean Architecture strictly. The dependency rule is
absolute: outer layers depend on inner layers, never the reverse.

- `src/reveille/domain/` — pure Python dataclasses and the ranking
  engine. No framework imports, no I/O.
- `src/reveille/adapters/` — `GitReader` (the only layer that imports
  GitPython) and `Renderer` (the only layer that imports Jinja2 and
  Plotly).
- `src/reveille/services/` — the `generate_report` orchestrator.
  No knowledge of infrastructure libraries.
- `src/reveille/cli.py` — argument parsing and progress display only.
  No business logic.

New behaviour belongs in the layer that owns its concern. Domain logic
that acquires a framework import is a layering violation.

## Submitting Pull Requests

All pull requests must target the `main` branch. The CI pipeline runs
`ruff`, `mypy`, and `pytest` across Python 3.11 and 3.12. All three
must pass. A pull request will not be merged if any check fails.

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
