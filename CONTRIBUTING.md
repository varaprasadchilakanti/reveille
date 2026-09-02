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

> **Poetry 2.2 or newer is required from v0.8.0.** The lock file is written in
> `lock-version 2.1`, which Poetry 1.x reads only with a warning, and
> `make check-lock-sync` runs `poetry check --lock` — which Poetry 1.x spells
> differently and cannot complete anyway, because its bundled classifier list
> predates Python 3.14.
>
> If Poetry came from a distribution package (`which poetry` shows
> `/usr/bin/poetry`), **`poetry self update` will not work**: it tries to write
> into a system-managed directory and fails with a permission error, and forcing
> it with `sudo` would fight the package manager. Install it user-scope instead.
> It shadows the system copy without removing it, provided `~/.local/bin`
> precedes `/usr/bin` on your `PATH`:
>
> ```console
> $ pipx install "poetry==2.4.2"
> $ poetry --version          # Poetry (version 2.4.2)
> ```
>
> The pin moved for three reasons, not one: `poetry check` now runs at all,
> which closes the last half of a long-standing audit finding; the lock format
> now matches what Dependabot writes, so its pull requests stop flipping the file
> between two formats; and `SOURCE_DATE_EPOCH` is honoured, which the previous
> version silently ignored.


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

Reveille supports **every non-EOL CPython release at or above 3.11**. As of the 0.8.0
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

Releases follow [RELEASE.md](RELEASE.md).

## Submitting Pull Requests

All pull requests must target the `main` branch.

CI runs a `lockfile` job first, and every other job depends on it: it asserts
`poetry.lock` is valid TOML using only the standard library, because a lock
that cannot be parsed is exactly what stops Poetry running, so a check needing
Poetry could never report it. The remaining jobs then run in parallel —
`ruff`, `mypy`, and `pytest` across every supported Python version (see
[Supported Python versions](#supported-python-versions)) — alongside a
packaging check, a version-consistency check, a licence-consistency check, and
a check that `poetry.lock` still agrees with `pyproject.toml`. All must pass.
A pull request will not be merged if any check fails.

`make ci` runs the same set locally.

One thing worth knowing before you hit it: `poetry.lock` is marked `-merge` in
`.gitattributes`, so Git will not write conflict markers into it. A conflict
there prints `warning: Cannot merge binary files: poetry.lock` and leaves your
own version in place. That is deliberate — the file is generated, and "keep
both sides" silently duplicates TOML keys. Resolve it by regenerating:
`poetry lock --no-update`.

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

Reveille is licensed under the [Apache Licence 2.0](LICENSE) from version
0.8.0 onward. Versions up to and including 0.7.0 were released under the MIT
Licence, and that grant is unaffected.

New source files should carry the two-line SPDX header the rest of the tree
uses, so that a file still declares its licence if it is ever separated from
this repository:

```python
# SPDX-FileCopyrightText: 2026 Your Name
# SPDX-License-Identifier: Apache-2.0
```

`make check-licence` asserts that `LICENSE`, `pyproject.toml` and
`reveille.__licence__` agree, and `tests/unit/test_licence.py` asserts that
every source file carries a header naming the same licence.

## Contributor Licence Agreement

Pull requests to this repository require a contributor licence agreement.
Filing an issue, reporting a bug, or joining a design discussion does not.

**Read [CLA.md](CLA.md).** Its first section explains the whole thing in plain
English and takes about two minutes.

### The short version

You keep the copyright in everything you write. The agreement is a
**licence**, not an assignment — nothing is transferred, and you remain free
to reuse your own code anywhere else on any terms you like. What you grant is
permission broad enough that this project can distribute your contribution
under its current licence *and* under a different licence later, if the
project ever changes licence.

In return, [CLA.md](CLA.md) §2.3(b) fixes a floor: whatever else happens, your
contribution stays available under the licence the project was using on the day
you contributed. That licence can be added to. It cannot be taken away.

Apache-2.0 §5 already licenses an ordinary pull request under Apache-2.0
without any of this. The agreement exists for one reason: §5 licenses your
contribution under *that* licence and only that licence, so a future licence
change would otherwise require tracking down every past contributor. The Linux
Foundation lists this as one of the three standard reasons a project adopts a
CLA — see
<https://bestpractices.linuxfoundation.org/ip/contribution-mechanisms-cla.html>.

If you would rather contribute on different terms, say so in the pull request
and it will be discussed on its merits rather than refused automatically.

### How to accept it

Two steps, both of which you are probably close to doing already.

**1. Sign off your commits.** Every commit in the pull request needs a
`Signed-off-by` trailer:

```bash
git commit --signoff -m "fix(cli): correct exit code on missing config"
```

To add it to commits you have already made:

```bash
git rebase --signoff main
```

Git deliberately has no configuration option that turns `--signoff` on by
default — `git commit --help` states: *"Git does not (and will not) have a
configuration variable to enable the --signoff command line option by
default"*. (`format.signOff` affects `git format-patch`, not `git commit`.)
If you want it automatic, use an alias or a hook:

```bash
git config --local alias.ci "commit --signoff"
```

The trailer means you certify the
[Developer Certificate of Origin 1.1](https://developercertificate.org/) — that
you actually wrote the code, or have the right to submit it. The verbatim text
is in [docs/cla/DCO.txt](docs/cla/DCO.txt).

**2. Tick the box in the pull request description.** The pull request template
carries this line:

```
- [ ] I have read [CLA.md](CLA.md) and I accept the Reveille
  Contributor Licence Agreement, version 1.0 (`Reveille-CLA-1.0`), for the
  contributions in this pull request and for my future contributions to this
  project. My commits are signed off (`git commit --signoff`) under the
  Developer Certificate of Origin 1.1.
```

Change `[ ]` to `[x]`. Do not edit the wording — the `cla` CI job matches on
the version identifier, and an altered line will not be recognised.

That is the whole process. There is no form, no email, no external service and
no account to create.

### Which version applies

The agreement is versioned. The version identified in your pull request
checkbox is the version that governs your contribution. Superseded versions
stay in [docs/cla/](docs/cla/) and in this repository's Git history, so it is
always possible to establish which text a given contribution was made under.
Changing the agreement never changes the terms of a contribution already made.

### What is recorded about you

Nothing beyond what you publish yourself.

This project keeps **no signature register**: no `signatures.json`, no
database, no third-party CLA service. The record of your acceptance is the
pull request and your own commit trailers, which live on GitHub and in this
repository's Git history. The only personal data involved is the name and
email address you chose to put in your own commits.

If you do not want your email address to be public, set Git to use a GitHub
no-reply address before you commit — see
[GitHub's email addresses reference](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference).
A signed-off commit with a no-reply address is accepted.

Please note that Git history is append-only in practice: once a commit is
merged and cloned, the name and email in it cannot realistically be removed
from every copy. The Developer Certificate of Origin says the same thing in
its clause (d). Do not put anything in a commit that you would not want
published permanently.

[PRIVACY.md](PRIVACY.md) sets out exactly what is held, why, for how long, and
what can and cannot be undone — including a straight answer about erasure from
Git history. Questions or requests about personal data go to the address given
there.

> **This project's maintainer is not a lawyer, and none of the above is legal
> advice.** [CLA.md](CLA.md) is adapted from published agreements whose authors
> permit adaptation; the adaptation has not been reviewed by counsel. If the
> agreement matters to your employer, have them read it.
