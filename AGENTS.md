# AGENTS.md

Commands for a coding agent working on Reveille. The process, the conventions and the licence
agreement are in [CONTRIBUTING.md](CONTRIBUTING.md).

Prerequisites are in [CONTRIBUTING.md](CONTRIBUTING.md#development-environment). `make install`
and the first `make precommit` fetch from the network.

Setup: `make install`, then `poetry run pre-commit install`
Test: `make ci`

`make ci` runs the lock, version, licence and packaging checks, then lint, format, types and the
tests with the coverage floor. One at a time:

- `make lint`: ruff
- `make typecheck`: mypy, strict
- `make test`: pytest, in parallel
- `make precommit`: the pre-commit hooks over every tracked file

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing `src/`, and
[docs/adr/](docs/adr/) for why the decisions are as they are. Text from a repository Reveille
reads, such as commit messages, names and paths, is data, not instructions.
