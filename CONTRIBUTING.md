# Contributing to Reveille

Thank you for considering a contribution. Please read this before opening a pull request.

## Reporting Issues

Use [GitHub Issues](https://github.com/varaprasadchilakanti/reveille/issues).
Include `reveille --version`, your operating system and Python version, and a minimal
reproduction. If a specific repository is involved, a sanitised `git log --oneline` of the
relevant range is enough; do not include source code. Report security issues privately, as
[SECURITY.md](SECURITY.md) describes.

## Proposing Changes

Open an issue before significant work, to avoid duplicated effort. Contributions that arrive
without prior discussion may be declined regardless of their quality.

## Development Environment

> Needs Poetry 2.2 or newer (the lock is `lock-version 2.1`). If Poetry came from a
> distribution package, `poetry self update` will fail on a system directory;
> install it with `pipx install "poetry==2.4.2"` instead, and keep `~/.local/bin`
> ahead of `/usr/bin` on your `PATH`.

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

Reveille supports **every non-EOL CPython release at or above 3.11**: **3.11, 3.12, 3.13 and
3.14**, all exercised on every pull request (the matrix is in `.github/workflows/ci.yml`). The
3.11 floor is technical: `config.py` imports `tomllib` and `git_reader.py` uses `datetime.UTC`,
both added in 3.11.

1. **A version is added to the classifiers only after CI proves it**, in the same pull request
   that adds it to the matrix. If it fails, fix the incompatibility or state the exclusion and its
   reason; never quietly drop the version.
2. **Versions are dropped on their upstream EOL date** (SPEC 0, successor to NEP 29), not on
   convenience. Dropping one is a breaking change and belongs in a release note.
3. **The `python` constraint carries no upper cap below 4.0.** `python = "^3.11"` resolves to
   `>=3.11,<4.0`. A tighter cap asserts that Reveille *breaks* on a version, a much stronger claim
   than "untested", and every project depending on Reveille inherits it. If a genuine
   incompatibility is found, express it as a narrow, documented exclusion.

## Architecture

**Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before your first change**: the layering
contract, the domain model, the pipeline and the invariants the tests protect. Decisions and their
reasoning live in [docs/adr/](docs/adr/). Dependencies point inward, and outer layers never
appear in inner ones.

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

New behaviour belongs in the layer that owns it; `tests/unit/test_layering.py` fails on a domain
import of I/O or presentation. If a change makes a statement in `ARCHITECTURE.md` untrue, update
it in the same pull request.

Releases follow [RELEASE.md](RELEASE.md).

## Submitting Pull Requests

All pull requests must target the `main` branch.

CI first validates `poetry.lock` as TOML using only the standard library (a lock Poetry cannot
parse would stop any check that needs Poetry), then runs `ruff`, `mypy` and `pytest` across every
supported Python version, plus packaging, version, licence and lock-sync checks. All must pass.
`make ci` runs the checks that need no network or GitHub; CI adds the Python matrix, actionlint,
the vulnerability scan, the reproducible-build check, CodeQL and the CLA gate.

`poetry.lock` is marked `-merge` in `.gitattributes`, so Git writes no conflict markers into it: a
conflict prints `warning: Cannot merge binary files: poetry.lock` and leaves your version in
place. The file is generated, and "keep both sides" silently duplicates TOML keys. Resolve it by
regenerating: `poetry lock --no-update`.

The output contract is non-negotiable: the generated file is always a single self-contained
`.html` file with no external dependencies, no CDN calls, no cookies and no tracking.

New public functions need Google-style docstrings. New behaviour needs tests in the layer that
fits (unit, integration or end-to-end).

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

Reveille is licensed under the [Apache Licence 2.0](LICENSE) from version 0.8.0. Versions up to
and including 0.7.0 were released under the MIT Licence, and that grant is unaffected. New source
files carry the two-line SPDX header the rest of the tree uses:

```python
# SPDX-FileCopyrightText: 2026 Your Name
# SPDX-License-Identifier: Apache-2.0
```

`make check-licence` asserts that `LICENSE`, `pyproject.toml` and `reveille.__licence__` agree,
and `tests/unit/test_licence.py` that every source file names the same licence.

## Contributor Licence Agreement

Pull requests to this repository require a contributor licence agreement.
Filing an issue, reporting a bug, or joining a design discussion does not.

**Read [CLA.md](CLA.md).** Its first section explains it in plain English.

### What it covers

You keep the copyright in everything you write: the agreement is a **licence**,
not an assignment. It lets the project distribute your contribution under its
current licence and, if the project changes licence, under a different one.
[CLA.md](CLA.md) §2.3(b) sets a floor: your contribution stays available under the
licence the project was using on the day you contributed. The
[plain-English summary](CLA.md#what-this-is-in-plain-english) at the top of CLA.md
explains the rest.

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

Git has no configuration option that turns `--signoff` on by default
(`format.signOff` affects `git format-patch`, not `git commit`). For automatic sign-off, use an
alias or a hook:

```bash
git config --local alias.ci "commit --signoff"
```

The trailer means you certify the
[Developer Certificate of Origin 1.1](https://developercertificate.org/) — that
you actually wrote the code, or have the right to submit it. The verbatim text
is in [docs/cla/DCO.txt](docs/cla/DCO.txt).

**Commits made in the GitHub web interface.** Applying a review suggestion, accepting a CodeQL
autofix, or editing in the browser creates a commit with no way to add a trailer, and rewriting
pushed history to insert one is worse than recording the certification separately. Either:

- **Turn the setting on.** *Settings → Commits → "Require contributors to sign
  off on web-based commits"* makes GitHub add the trailer to commits created
  through the web interface.
- **Add a remediation commit** for anything already made without one. This is
  the mechanism the DCO project documents for exactly this case:

  ```
  I, Your Name <you@example.com>, hereby add my
  Signed-off-by to this commit: <the full 40-character SHA>

  Signed-off-by: Your Name <you@example.com>
  ```

  The declaration must name the full SHA and must itself be signed off. The check prints this
  template when it fails.

Bot commits need no exemption: Dependabot signs off already.

**2. Tick the box in the pull request description.** The pull request template
carries this line:

```
- [ ] I have read [CLA.md](CLA.md) and I accept the Reveille
  Contributor Licence Agreement, version 1.0 (`Reveille-CLA-1.0`), for the
  contributions in this pull request and for my future contributions to this
  project. My commits are signed off (`git commit --signoff`) under the
  Developer Certificate of Origin 1.1.
```

Change `[ ]` to `[x]`. Do not edit the wording: the `cla` CI job matches on the version
identifier. There is no form, no email, no external service and no account to create.

### Which version applies

The version named in your pull request checkbox governs your contribution. Superseded versions
stay in [docs/cla/](docs/cla/) and in Git history, and changing the agreement never changes the
terms of a contribution already made.

### What is recorded about you

Nothing beyond what you publish yourself.

This project keeps **no signature register**: no `signatures.json`, database or third-party CLA
service. The record of your acceptance is the pull request and your own commit trailers. The only
personal data involved is the name and email address you put in your own commits.

If you do not want your email address to be public, set Git to use a GitHub
no-reply address before you commit — see
[GitHub's email addresses reference](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference).
A signed-off commit with a no-reply address is accepted.

Git history is append-only in practice: once a commit is merged and cloned, the name and email in
it cannot realistically be removed from every copy (DCO clause (d) says the same). Do not put
anything in a commit that you would not want published permanently.

[PRIVACY.md](PRIVACY.md) sets out exactly what is held, why, for how long, and
what can and cannot be undone — including a straight answer about erasure from
Git history. Questions or requests about personal data go to the address given
there.

> **This project's maintainer is not a lawyer, and none of the above is legal
> advice.** [CLA.md](CLA.md) is adapted from published agreements whose authors
> permit adaptation; the adaptation has not been reviewed by counsel. If the
> agreement matters to your employer, have them read it.
