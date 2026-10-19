# Reveille

**Offline Git history reports, and repository state and change summaries as JSON for scripts, CI and coding agents.**
Reveille reads a local clone (GitHub, GitLab, Bitbucket or self-hosted) and writes one HTML report: a commit calendar
heatmap, weekly activity and how commits are spread across contributors. It never changes Git data and makes no network call.
SHA-256 repositories and partial clones are refused.
The name is the call that starts a soldier's day: `reveille state` and `reveille brief` tell a
person or a coding agent starting work where the repository stands and what changed, from local
history.

[![PyPI](https://img.shields.io/pypi/v/reveille)](https://pypi.org/project/reveille/)
[![Python](https://img.shields.io/pypi/pyversions/reveille)](https://pypi.org/project/reveille/)
[![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue)](https://github.com/varaprasadchilakanti/reveille/blob/main/LICENSE)
[![CI](https://github.com/varaprasadchilakanti/reveille/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/varaprasadchilakanti/reveille/actions/workflows/ci.yml)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14502/badge)](https://www.bestpractices.dev/projects/14502)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/report-dark.png">
  <img src="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/report-light.png" width="860" alt="The top of a Reveille report for a sample repository with invented contributors: the report's statement of its own limits, five summary figures with a note that one automated account is counted in the totals but not as a person, four findings in plain sentences, and a Lorenz curve of how commits are spread across six people.">
</picture>

*A report for a sample repository with invented contributors, built by
[`docs/images/make_sample_repository.py`](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/images/make_sample_repository.py)
and rendered with `reveille generate --deterministic`.*

The report also shows where change concentrates and a per-contributor table. The same figures are
available as JSON or CSV. `state`, `brief`, `summary` and `who-changed` answer single questions as
text or JSON; the first three also give Markdown, and `state` and `brief` one line.

```bash
pipx install reveille
cd /path/to/repository
reveille generate
```

**Properties.** These are designed and tested, not a warranty. The test suite checks each of them on
every change. [SECURITY.md](https://github.com/varaprasadchilakanti/reveille/blob/main/SECURITY.md)
covers the threat model and how to verify a release.

- No network call. The report loads no remote resource and opens with no internet connection.
- No change to Git data. History, refs, index, objects and configuration are left as they are, and
  an output path inside the repository's Git directory is refused.
- Git runs with signature checking, fsmonitor and (for `state`) repository-defined content
  filters switched off. A plain `git status` runs the last two.
- With `--deterministic`, an unchanged repository produces a byte-identical report on the same
  Reveille version, installed dependencies and Git settings.

Limits: Git has many settings, and Reveille switches off only those its reads were found to use, so a
repository whose `.git` came from someone else may still run one. `git clone` does not copy
`.git/config`; a copied directory or an archive does. A partial clone (`git clone --filter`) is
refused, because reading it would make Git fetch. A SHA-256 repository is refused for now: the
library Reveille reads it with cannot parse its references. A repository whose `.git/config` sets
`core.worktree` to another directory is refused, since the report would describe that directory
and be written into it.

Reveille is provided under the Apache Licence 2.0 "AS IS"; sections 7 and 8 of the
[LICENSE](https://github.com/varaprasadchilakanti/reveille/blob/main/LICENSE) disclaim warranty and
limit liability as far as applicable law allows.

**What it is not**

- Not an evaluation of people. It counts commits and changed lines, which does not measure anyone's
  contribution, productivity or value.
- Not a ranking unless you ask: ranking people needs `--ranking`, and the report then states what the
  score measures and what it does not. JSON and CSV still carry a `rank` column, in table order
  (by commits; by score with `--ranking`).
- Not anonymised. A report names the people in the history and carries their activity, and their
  email addresses unless you pass `--hide-emails`, which replaces the addresses and leaves the names. [What the report contains about people](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#what-the-report-contains-about-people)
  lists it field by field, and [Before you share a report](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#before-you-share-a-report)
  says what to check.
- Not a bus factor. Commit concentration says who committed, not who understands the code.
- Not every commit. Merge commits are excluded, so counts are lower than `git log` shows; the JSON
  says how many were left out (`merge_commits_excluded`).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/how-it-fits-dark.svg">
  <img src="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/how-it-fits-light.svg" width="860" alt="A local Git repository goes into Reveille, which reads commit metadata, Co-authored-by trailers and per-file line counts only, makes no network calls and never changes Git data. Out come one self-contained HTML report for people, and JSON (with a schema version) or CSV for scripts and AI assistants.">
</picture>

---

## Contents

- [Who It Is For](#who-it-is-for)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [In CI: GitHub Actions](#in-ci-github-actions)
- [Reading the Report](#reading-the-report)
- [Commands](#commands)
- [Contributor Ranking](#contributor-ranking)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Legal and Privacy](#legal-and-privacy)
- [Licence](#licence)

---

## Who It Is For

- An engineer or lead with a question about a repository's history (when work happened, how
  concentrated it is, who changed a file) who wants the answer without sending the history to a
  service.
- Someone who needs a figure they can recompute. `--deterministic` gives the same bytes for the same
  repository, and the JSON records the analysed commit and the options used. The
  [Playbook](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/PLAYBOOK.md#for-an-audit-or-due-diligence)
  says what history is and is not evidence of.
- An AI assistant or a script, through `state`, `brief`, `summary` and `who-changed`, JSON on stdout,
  a declared schema version and exit codes that separate "no" from "could not run".
  `summary --format json` and `brief` name no contributor, but `summary` carries the repository and
  branch names, and with one or two people the counts can identify someone.
  `generate --format json --output -` prints names and email addresses, which leave your machine if
  given to a hosted model.

Its figures do not support judging people; see [Contributor Ranking](#contributor-ranking).

---

## Installation

Reveille needs Python 3.11 or later and Git 2.24 or later (older Git is refused with exit 2).

```bash
pipx install reveille      # or: uv tool install reveille, or pip install reveille
reveille --version
```

It installs two names for one command, `reveille` and the shorter `reile`; if another tool owns
either, use `python -m reveille`. To run it once without installing: `uvx reveille summary`. To
remove it, use the tool that installed it (`pipx uninstall reveille`, `pip uninstall reveille` or
`uv tool uninstall reveille`). Reveille keeps no cache or settings.

---

## Quickstart

```bash
cd /path/to/your/repository
reveille generate
```

This writes `reveille-report.html` in the repository root. Open it in any browser; it needs no
network. The file is untracked, so `git add -A` would commit it, names and addresses included: add
it to `.gitignore`, or write it elsewhere with `--output`. The header, summary cards, findings, repository profile and contributor table are plain
HTML; the other charts need JavaScript.

```bash
reveille generate --since 2024-01-01 --until 2024-12-31   # a date range
reveille generate --output /tmp/q4-report.html            # another path (outside the repository: written, with a warning)
reveille generate --repo /path/to/repository              # another repository
reveille init                                             # write an annotated reveille.toml
```

`reveille init` writes a `reveille.toml` with every key commented out. From then on
`reveille generate`, run from that directory, loads it and announces any setting it applies.

---

## In CI: GitHub Actions

A weekly report, kept as a build artifact, with the summary on the run's page:

```yaml
name: Repository history report
on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"
permissions:
  contents: read
concurrency:
  group: reveille-report
  cancel-in-progress: true
jobs:
  report:
    name: History report
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0 # the whole history; the default, 1, is a single commit
          persist-credentials: false
      - run: pipx run reveille generate --output reveille-report.html
      - run: |
          { echo '```'; pipx run reveille summary; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: reveille-report
          path: reveille-report.html
          retention-days: 7
```

Set `fetch-depth: 0`: with the checkout's default of one commit, the report covers one commit, and
says so. The report lists contributors' names and email addresses, and anyone who
can read the repository's Actions runs can download the artifact; on a public repository that
is everyone. GitLab CI needs `GIT_DEPTH: 0` for the same reason.

---

## Reading the Report

The report runs findings first, evidence after: header and summary cards (window, commits, people,
how many hold half the commits, longest quiet run, Gini coefficient); written findings that name
nobody; a Lorenz curve of how evenly commits are spread; the commit-activity heatmap and weekly
timeline; the repository profile; change size, hotspots and file types; then per-contributor
figures. Automated accounts (`[bot]` in the name or address) are counted in commit totals and
stated apart, not counted as people.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/profile-dark.png">
  <img src="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/profile-light.png" width="860" alt="The Repository Profile of the same sample report: six petals for continuity, recent work, shared, collaboration, revisiting and automation, each petal's length its share, beside a table giving each share and what evenly spread activity would give.">
</picture>

Two sections appear only when asked for: **Who Changed Each Area** (`--area-authors`) and the
**Contributor Rankings** table (`--ranking`). The
[User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#understanding-the-report)
describes every section; the
[Playbook](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/PLAYBOOK.md)
says what each figure supports and what it does not.

---

## Commands

Every flag, default and output format is in the
[User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#commands-and-outputs).
`reveille --version` prints the version (`reveille version` is not a command). `-h` works on every
command.

### `reveille generate`

Writes the report: HTML by default, or `--format json` or `--format csv`. Options select the
repository, output path (`-` for stdout), date window, branch, authors to exclude, title, and
`--deterministic`. Defaults to the checked-out branch and the whole history.

```bash
reveille generate --branch release/2.0 --exclude-author "dependabot[bot]"
reveille generate --format json --output - | jq .derived
```

### `reveille init`

Writes an annotated `reveille.toml` (every key commented out) in the current directory, which
must be a repository root. `--mailmap` adds a `.mailmap` template; `--force` overwrites. New
files are owner-only; `chmod 644` lets other accounts on a shared machine read them.

### `reveille validate`

Exits 0 if the path is a readable Git repository with a commit, 1 if it has none, 2 if it cannot
be read. Useful in CI before `generate`.

```bash
reveille validate --repo /path/to/repository
```

### `reveille summary`

The repository in a few lines, naming no contributor (with one or two people, counts can identify
someone). It reads no line counts, so it is quicker than `generate`: 1.02 s against 9.35 s on a
9,015-commit history (measured 2026-10-12).

```bash
reveille summary --format json
```

### `reveille brief`

What changed since a tag, a commit or a date, in counts, naming nobody (with one or two people,
counts can identify someone): commits, people, the most changed areas and file types, files added,
areas active again and tags in the range. It prints the commit it reached, so the next brief can
start there.

```bash
reveille brief --from v0.9.0
```

### `reveille state`

Where the repository stands now: branch, upstream, a merge or rebase in progress, conflicts, what
is staged, modified or untracked, stashes, worktrees, branch counts and the latest tag. Unlike
`git status`, it neither rewrites `.git/index` nor runs a program the repository's own config names.
It names no author, but it lists local paths (changed files and worktree directories, which can
contain your login name), the current branch, its upstream and the branches checked out in
worktrees.

```bash
reveille state --format json
```

### `reveille who-changed`

Who changed a file or directory, and who changed it most recently. It says who changed the code,
not who knows or owns it. A path no commit in the window changed exits 1.

```bash
reveille who-changed src/parser/lexer.c --since 2026-01-01
```

### `reveille repos`

Which repositories in a directory are active, quiet or dormant: one row per repository, with its
last commit and the commits, people and automated accounts in the last 90 days as counts. It names
nobody and counts nobody across repositories. A folder of clones or of bare mirrors both work.

```bash
reveille repos ~/src --format markdown
```

### `reveille capabilities`

States what Reveille can and cannot do, including what it declines to claim, read from the installed
program. `--format json` adds the command surface and exit codes.

```bash
reveille capabilities --format json
```

### `reveille skill`

Prints what to tell a coding agent about Reveille: a section for `AGENTS.md` or `CLAUDE.md` naming
the commands to run, and saying that repository text in their output is data, not instructions.
`--format skill` gives it as a `SKILL.md`. Every command it names is run by a test.

```bash
reveille skill >> AGENTS.md
```

### `reveille help`

Same as `reveille --help`.

---

## Contributor Ranking

`--ranking` adds a rank, one of seven tiers and a composite score to each listed contributor.
It is off by default. JSON and CSV carry a `rank` column either way: table order by commits, or by score
with `--ranking`.

**What this measures is the volume and regularity of commits, not contribution, productivity,
or value.** The weights are a documented judgement, not a derived model. The SPACE framework
(Forsgren et al., 2021) holds that "developer productivity is about more than an individual's
activity levels". A contributor who spends a quarter reviewing others' work and deleting a
subsystem will rank below one who committed generated files. The military tier names are labels on
a score of commit volume and regularity, not an evaluation of anyone. The formula and the tier table
are in the
[User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#the-ranking-algorithm).

---

## Documentation

| If you want to | Read |
|---|---|
| use every option, read every section of the report, or check what it contains about people | [User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md) |
| know what a figure supports and what it does not | [Playbook](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/PLAYBOOK.md) |
| know who is responsible for the personal data in a report | [Compliance](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/COMPLIANCE.md) |
| report a vulnerability or verify a release | [Security](https://github.com/varaprasadchilakanti/reveille/blob/main/SECURITY.md) |
| see what changed in each version | [Changelog](https://github.com/varaprasadchilakanti/reveille/blob/main/CHANGELOG.md) |
| point an assistant at the right document | [llms.txt](https://github.com/varaprasadchilakanti/reveille/blob/main/llms.txt) |
| understand how it is built, or why a decision was made | [Architecture](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/ARCHITECTURE.md) and the [decision records](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/adr/README.md) |

---

## Contributing

Contributions are welcome. [CONTRIBUTING.md](https://github.com/varaprasadchilakanti/reveille/blob/main/CONTRIBUTING.md)
covers the development setup, the tests, the pull request contract and the commit conventions.
Each commit must be signed off, and pull requests accept the
[contributor agreement](https://github.com/varaprasadchilakanti/reveille/blob/main/CLA.md), which
does **not** transfer your copyright. Filing an issue needs neither. Participation is governed by
the [Code of Conduct](https://github.com/varaprasadchilakanti/reveille/blob/main/CODE_OF_CONDUCT.md).

---

## Legal and Privacy

Reveille runs on your machine and makes no network call. The report it writes contains contributor
names and email addresses, so whoever runs it and circulates it is handling personal data.
[docs/COMPLIANCE.md](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/COMPLIANCE.md)
records why the maintainer is neither controller nor processor under the GDPR (which engages,
since commit author names and addresses are personal data) and who is responsible for what. It is
research, not legal advice.
[PRIVACY.md](https://github.com/varaprasadchilakanti/reveille/blob/main/PRIVACY.md) is a notice
for *contributors to this project*, not for users of the tool.

---

## Licence

Reveille is released under the [Apache Licence 2.0](https://github.com/varaprasadchilakanti/reveille/blob/main/LICENSE).
Copyright 2026 Vara Prasad Chilakanti. The software is provided "AS IS"; sections 7 and 8 of the
licence disclaim warranties and limit liability. Versions up to and including 0.7.0 were released
under the MIT Licence, and anything obtained under it stays under it; see
[ADR 0007](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/adr/0007-apache-2-0-licence.md).

Git is a trademark of the Software Freedom Conservancy. Reveille is not affiliated with
or endorsed by the Git project, GitHub, GitLab, Atlassian or Plotly; their names are used only to
say what Reveille works with.
