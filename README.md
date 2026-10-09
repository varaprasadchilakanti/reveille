# Reveille

**Commit-history analytics for a local Git repository. It runs offline and sends nothing anywhere.**

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

Reveille reads a repository's Git history on your machine and writes one self-contained HTML
report: a contribution calendar, weekly activity, how evenly commits are spread across
contributors, and a per-contributor table. The same figures are available as JSON or CSV for
scripts and AI assistants.

```bash
pipx install reveille
cd /path/to/repository
reveille generate
```

**What it is designed and tested to do.** Each of these is checked by the test suite on every change.
[SECURITY.md](https://github.com/varaprasadchilakanti/reveille/blob/main/SECURITY.md) covers the threat model and how to verify a release.

- **No network calls.** The report loads no remote resource and opens with no internet connection.
- **No changes to Git data.** History, refs, index, objects and configuration are never changed,
  and an output path inside the repository's Git directory is refused.
- **Same input, same output.** With `--deterministic`, an unchanged repository produces a
  byte-identical report from the same Reveille version.

One limit: Reveille runs Git, and Git obeys a repository's own `.git/config`, which can name a
program to run. Such a program is outside these properties. `git clone` does not copy that file;
a copied directory or an archive does. A partial clone (`git clone --filter`) is refused, because
reading it would make Git fetch.

Reveille is provided under the Apache Licence 2.0 "AS IS", without warranties or conditions of
any kind; sections 7 and 8 of the [LICENSE](https://github.com/varaprasadchilakanti/reveille/blob/main/LICENSE) set out the disclaimer of warranty and the
limitation of liability. The properties above describe what the software is designed and tested
to do; they are not a warranty.

**What it is not.**

- **Not a measure of performance.** It counts commits and changed lines. It does not measure
  anyone's contribution, productivity or value.
- **Not a ranking, unless you ask.** Ranking people needs `--ranking`, and the report then states
  what the score measures and what it does not.
- **Not anonymous.** Every report names the people in the history and carries their email
  addresses and activity. [What the report contains about people](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#what-the-report-contains-about-people)
  lists it field by field, and [Before you share a report](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#before-you-share-a-report)
  says what to check.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/how-it-fits-dark.svg">
  <img src="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/how-it-fits-light.svg" width="860" alt="A local Git repository goes into Reveille, which reads commit metadata and per-file line counts only, makes no network calls and never changes Git data. Out come one self-contained HTML report for people, and JSON (with a schema version) or CSV for scripts and AI assistants.">
</picture>

**For AI assistants and scripts.** `reveille summary --format json` describes the repository in
about 2 KB and names no contributor; it does carry the repository and branch names, and with one
or two people its figures describe identifiable individuals. `reveille capabilities --format json` describes what the tool can and
cannot do. `reveille generate --format json --output -` prints every figure, including contributor
names and email addresses; given to a hosted model, they leave your machine.

---

## Contents

- [Who It Is For](#who-it-is-for)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Reading the Report](#reading-the-report)
- [CLI Reference](#cli-reference)
- [Output Formats](#output-formats)
- [Contributor Ranking](#contributor-ranking)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Legal and Privacy](#legal-and-privacy)
- [Licence](#licence)

---

## Who It Is For

- **An engineer or lead with a question about a repository's history** — when work happened, how
  concentrated it is, who changed a file — who wants the answer without sending the history to a
  service. It reads any local Git repository, so Bitbucket, GitLab, GitHub and self-hosted
  repositories work alike.
- **Someone reviewing a codebase for an audit or due diligence**, who needs a figure they can
  reproduce: `--deterministic` gives the same bytes for the same repository, and the JSON records
  the analysed commit and the options used. The
  [Playbook](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/PLAYBOOK.md#for-an-audit-or-due-diligence)
  says what the history is and is not evidence of.
- **An AI assistant or a script**, through `summary`, `who-changed`, JSON on stdout, a declared
  schema version and exit codes that separate "no" from "could not run".

Its figures do not support judging people. The project's position on that is in
[Contributor Ranking](#contributor-ranking).

---

## Installation

Reveille needs Python 3.11 or later and Git (`git --version`).

```bash
pipx install reveille        # recommended: an isolated command-line tool
```

Or, equally:

```bash
pip install reveille
uv tool install reveille     # or run once without installing: uvx reveille generate
poetry add reveille          # inside a Poetry-managed project
```

Check it:

```bash
reveille --version
```

To remove it, use the tool that installed it: `pipx uninstall reveille`, `pip uninstall reveille`
or `uv tool uninstall reveille`. Reveille keeps no cache or settings of its own; it leaves only
the files you asked it to write.

---

## Quickstart

```bash
cd /path/to/your/repository
reveille generate
```

Reveille reads the local Git history and writes `reveille-report.html` in the repository root.
Open it in any browser; it needs no network. The header, summary cards, written findings,
repository profile and contributor table are plain HTML; the other charts need JavaScript.

A date range:

```bash
reveille generate --since 2024-01-01 --until 2024-12-31
```

Another output path (a path outside the repository is written, with a warning):

```bash
reveille generate --output /tmp/q4-report.html
```

Another repository:

```bash
reveille generate --repo /path/to/repository
```

A configuration file, so options need not be repeated:

```bash
reveille init
```

This writes an annotated `reveille.toml` with every key commented out. From then on
`reveille generate`, run from that directory, loads it and prints which settings it applied.

---

## Reading the Report

The report reads top to bottom, findings first and evidence after:

1. **Header, notice and summary cards** — the window, branch and remote; total commits; the
   number of people; how many of them hold half the commits; the longest quiet run; the Gini
   coefficient. Automated accounts (`[bot]` in the name or address) are counted in the commit
   totals and stated under the cards, not counted as people.
2. **What the History Shows** — a few sentences generated by fixed rules, naming nobody.
3. **Contribution Distribution** — a Lorenz curve and the Gini: how evenly commits are spread
   across people.
4. **Commit Activity Heatmap** and **Weekly Commit Timeline** — when the work happened.
5. **Repository Profile** — six shares (continuity, recent work, shared, collaboration,
   revisiting, automation) drawn as petals beside a table, each against what chance would give
   where that can be computed.
6. **Change Size per Commit**, **Where Change Concentrates** and **Change by File Type** — how
   big changes are, which paths absorb them, and what kind of files they touch.
7. **Per-Contributor Commit Frequency**, **Contributors** and **Contribution Breakdown** — the
   figures per person.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/profile-dark.png">
  <img src="https://raw.githubusercontent.com/varaprasadchilakanti/reveille/main/docs/images/profile-light.png" width="860" alt="The Repository Profile of the same sample report: six petals for continuity, recent work, shared, collaboration, revisiting and automation, each petal's length its share, beside a table giving each share and what evenly spread activity would give.">
</picture>

Two sections appear only when asked for: **Who Changed Each Area** (`--area-authors`) and the
**Contributor Rankings** form of the table (`--ranking`).

Every section is described in the
[User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#understanding-the-report);
what each figure supports, and what it does not, is in the
[Playbook](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/PLAYBOOK.md).
Commit counts are lower than `git log` shows, because merge commits are excluded.

---

## CLI Reference

### `reveille generate`

Generates the HTML activity report for the target repository.

| Flag | Short | Type | Default | Description |
|---|---|---|---|---|
| `--repo` | `-r` | `PATH` | `.` (current directory) | Path to a Git repository: a working tree's root, or a bare repository (which needs `--output`, since its root is Git's own directory). |
| `--output` | `-o` | `PATH` | `reveille-report.html` in the repository root | Path for the generated file. Parent directories must exist. A path inside `.git`, or containing `..`, is refused; one outside the repository is written with a warning. `-` writes the report, in any format, to stdout, and nothing else goes there. |
| `--since` | | `DATE` | The first commit | Include only commits on or after this date. Accepts `YYYY-MM-DD`. A date before the first commit changes nothing: the days before a repository existed are not quiet days. |
| `--until` | | `DATE` | Today (UTC) | Include only commits on or before this date. Accepts `YYYY-MM-DD`. Without it, commits dated after today are counted in no figure, and the report and a note on stderr say how many. |
| `--branch` | `-b` | `TEXT` | The checked-out branch | Analyse commits reachable from this branch only. Defaults to whichever branch is currently checked out, which is not necessarily the repository's default branch. |
| `--exclude-author` | | `TEXT` | None | Exclude a person: every commit made under an address that a matching name or address was used with, and every address a `.mailmap` ties to it. Repeatable. |
| `--min-commits` | | `INT` | `1` | List only contributors with at least this many commits in the analysis window. Every figure still counts everyone, and the header says how many are listed. |
| `--title` | | `TEXT` | Repository name | Override the report title displayed in the HTML output. |
| `--ranking` | | Flag | Off | Include the contributor ranking table. **Off by default** — it scores and tiers named individuals, which is more than the figures support. Read [Contributor Ranking](#contributor-ranking) first. |
| `--no-ranking` | | Flag | Off | Explicitly omit the ranking table. Ranking is already off by default; this exists so existing invocations keep working. |
| `--area-authors` | | Flag | Off | Add a section listing who changed each of the most-changed directories, and when each was last changed. **Off by default**: it names people, by area. |
| `--limit` | | `INT` | None | Bound every list of people in JSON and CSV to this many. JSON states the full total and a `truncated` flag beside each list; a cut CSV is announced on stderr. For assistants: the full JSON of a large repository runs to hundreds of kilobytes. |
| `--area-depth` | | `INT` | `3` | Directory components that make an area for `--area-authors`. |
| `--format` | | `TEXT` | `html` | Output format. Accepted values: `html`, `json`, `csv`. `json` and `csv` write files at the same path stem as `--output`. |
| `--deterministic` | | Flag | Off | Produce byte-reproducible output. Pins `generated_at` and the end of the analysis window to the repository's own last commit rather than to the clock, so two runs over an identical repository produce identical bytes. |
| `--verbose` | | Flag | Off | Emit diagnostic logging to stderr. Does not change the report. |
| `--config` | `-c` | `PATH` | None | Path to a TOML configuration file. If omitted, `reveille.toml` in the current working directory is loaded automatically when present. Use this flag for non-standard file names or paths outside the repository root. CLI flags always take precedence over configuration file values. |

### `reveille init`

Scaffolds a fully annotated `reveille.toml` configuration file in the current directory. Every available key is present, commented out, and documented inline. Run this once before your first `reveille generate` invocation to produce a starting point you can edit rather than constructing the file from scratch.

| Flag | Short | Type | Default | Description |
|---|---|---|---|---|
| `--output` | `-o` | `PATH` | `./reveille.toml` | Destination path for the generated configuration file. |
| `--force` | | Flag | Off | Overwrite an existing file at the target path without prompting. |
| `--mailmap` | | Flag | Off | Generate an annotated `.mailmap` template at the repository root alongside `reveille.toml`. Documents two-field, three-field, and four-field format variants with real-world examples. An existing `.mailmap` is skipped with a message unless `--force` is also given, in which case it is overwritten. |

### `reveille --version` / `-v`

Prints the installed version string and exits. This is a global flag rather than
a subcommand — `reveille version` is not a valid invocation.

```bash
reveille --version
```

### `reveille validate`

Checks that the target path is a readable Git repository with at least one commit: exit 0 if so, 1 if it has none, 2 if it cannot be read. It takes no date options. Useful in CI before `generate`.

```bash
reveille validate --repo /path/to/repository
```

`validate` also accepts `--verbose`, which emits diagnostic logging to stderr
without changing the exit code or the normal output.

### `reveille summary`

The repository in a few lines, naming no contributor: window, totals, Gini, commit
concentration, longest quiet run, days since the last commit, the written
findings, and a notice that the figures need checking before a decision. It
reads no line counts, so on a large history it is several times faster than
`generate`. Takes `--repo`, `--since`, `--until`, `--branch`,
`--exclude-author`, `--deterministic` and `--format text|json`; it reads no
`reveille.toml`.

```bash
reveille summary
reveille summary --format json
```

### `reveille who-changed`

Who changed one file or directory in the window, and who changed it most
recently: for finding the person to ask about a bug, or a reviewer for a
change. Names are alphabetical, with no count or date per person; the five who
changed it most recently are shown separately; automated accounts and
co-authors are listed apart; every list is bounded by `--limit` (default 20).
It says who changed the code, not who knows or owns it. Takes the options of
`summary` plus `--limit`.

```bash
reveille who-changed src/parser/lexer.c
reveille who-changed src/parser --since 2026-01-01 --format json
```

A path that no commit in the window changed is a negative answer (exit 1). Renames are
not followed: history from before a rename belongs to the old path.

### `reveille capabilities`

Describes what Reveille can and cannot do — including, deliberately, the things
it refuses to claim. Written for a program as much as for a person: an agent or
a script can ask the installed binary directly rather than inferring from this
README.

| Flag | Short | Type | Default | Description |
|---|---|---|---|---|
| `--format` | | `TEXT` | `text` | Output format. Accepted values: `text`, `json`. |

```bash
reveille capabilities
reveille capabilities --format json
```

The JSON form carries `capabilities_version`, the tool version, the output
schema version, the guarantees that hold on every run, a `can` list, a `cannot`
list with what to use instead, the caveats that change how a number should be
read, every command with its options, and the exit-code contract. The command
surface and the exit codes are read from the running program rather than
restated, so they cannot drift from it.

### `reveille help`

Displays the top-level help text listing all available commands and global options. Equivalent to `reveille --help` and `reveille -h`. The short flag `-h` is available on every subcommand — for example, `reveille generate -h` displays the full flag reference for the generate command.

```bash
reveille help
```

---

## Output Formats

- **HTML** (default) — one self-contained file of about 4.9 MB, almost all of it the embedded
  chart library; it opens offline in any browser.
- **JSON** (`--format json`) — opens with `schema_version`, then `metadata`, `provenance` (the
  Reveille version, the analysed commit, whether a `.mailmap` was applied, whether the clone was
  shallow, and the filters as requested), the contributors and the `derived` figures. The scoring
  fields are present only with `--ranking`; a `rank` field, in table order, is always present. Full shape in the
  [User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#structured-output).
- **CSV** (`--format csv`) — the contributor table alone, UTF-8 with a byte-order mark so Excel
  reads it correctly. Columns: `rank` (table order; a ranking only with `--ranking`), `name`,
  `email`, `commits`, `lines_added`, `lines_deleted`, `net_lines`, `active_days`,
  `last_commit_date`, `co_authored_commits`. With `--ranking`, `designation`, `tier`,
  `composite_score` and `percentile` are added.

JSON and CSV are written at the `--output` path with the matching extension, or to stdout with
`--output -`. `--limit` bounds every list of people in them and says so.

---

## Contributor Ranking

`--ranking` adds a rank, one of seven tiers and a composite score to each listed contributor.
The score weights commit volume (30%), lines added plus deleted (25%), active days over the
window (25%) and recency (20%); the weights are configurable, and the tiers are percentiles of
the listed contributors in the window, not fixed thresholds.

**What this measures is the volume and regularity of commits — not contribution, productivity,
or value.** The weights are a documented judgement, not a derived model. The SPACE framework
(Forsgren et al., 2021) holds that "developer productivity is about more than an individual's
activity levels". A contributor who spends a quarter reviewing others' work and deleting a
subsystem will rank below one who committed generated files. The military tier names are a
visual device, not a rank. That is why ranking is off by default; the formula, the tier table and
what it does not measure are in the
[User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#the-ranking-algorithm).

---

## Configuration

`reveille init` writes an annotated `reveille.toml`; `reveille generate` loads `reveille.toml` from
the current directory when present, or the file given with `--config`. Command-line options
always win over the file. A key left out keeps its default.

```toml
[report]
title = "Repository Activity — Q4 2024"
output = "./reports/q4-2024.html"
branch = "main"
since = "2024-10-01"
until = "2024-12-31"
format = "html"

[filters]
min_commits = 2
exclude_authors = [
    "renovate[bot]",
]

[ranking]
enabled = false
```

An output path in the file that resolves outside the repository is refused, because a
configuration file is found automatically and may not be yours. Every key is in the
[TOML Configuration Reference](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#toml-configuration-reference).

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

Reveille runs entirely on your machine and sends nothing anywhere. The report it writes contains
contributor names and email addresses, so whoever runs it and circulates it is handling personal
data. [docs/COMPLIANCE.md](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/COMPLIANCE.md)
records why the maintainer is neither controller nor processor under the GDPR — which plainly
does engage, since commit author names and addresses are personal data — and sets out who is
responsible for what. It is research, not legal advice.
[PRIVACY.md](https://github.com/varaprasadchilakanti/reveille/blob/main/PRIVACY.md) is a notice
for *contributors to this project*, not for users of the tool.

---

## Licence

Reveille is released under the [Apache Licence 2.0](https://github.com/varaprasadchilakanti/reveille/blob/main/LICENSE).
Copyright 2026 Vara Prasad Chilakanti. The software is provided "AS IS"; sections 7 and 8 of the
licence disclaim warranties and limit liability. Versions up to and including 0.7.0 were released under the
MIT Licence, and anything obtained under it stays under it; the reasons for the change are in
[ADR 0007](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/adr/0007-apache-2-0-licence.md).

Git is a trademark of the Software Freedom Conservancy. Reveille is not affiliated with
or endorsed by the Git project, GitHub, GitLab, Atlassian or Plotly; their names are used only to
say what Reveille works with.
