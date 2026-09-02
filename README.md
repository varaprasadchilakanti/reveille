# Reveille

**A CLI tool that generates performance reports from local Git repositories — as self-contained HTML, structured JSON, and CSV.**

Reveille reads your repository's Git history and produces a single portable `.html` file containing interactive visualisations of contributor activity, commit trends, code volume, and repository health — with no server, no external API calls, and no configuration beyond the command itself. Open the output in any browser, share it over email, or drop it into a Confluence page without modification.

---

## Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [CLI Reference](#cli-reference)
- [Output Description](#output-description)
- [Contributor Ranking System](#contributor-ranking-system)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Contributing](#contributing)
- [Changelog](#changelog)
- [Licence](#licence)

---

## Overview

Reveille is designed for developers, engineering managers, and technical leads who need a production-grade, shareable retrospective from any Git repository — without configuring infrastructure or connecting to external services.

**What it produces:**

- Contribution heatmap with a GitHub-style year-navigable grid showing per-day commit activity. Year tabs allow switching between calendar years; a contributor dropdown surfaces per-contributor views alongside the aggregated default.
- Aggregate weekly commit timeline and per-contributor commit frequency chart, enabling direct comparison of burst contributors versus contributors with sustained low-volume engagement across the analysis window
- Per-contributor breakdowns covering commits, lines added and removed, and active day counts
- A structured ranking table assigning each contributor a tier designation based on weighted activity metrics
- Repository activity indicators including commit concentration, longest inactive streak, and consistency scores
- Machine-readable output in JSON (ranked contributor statistics and repository metadata) and CSV (contributor table with BOM encoding for Excel compatibility) via `--format json`, `--format csv`

**Design constraints that are non-negotiable:**

- The output is always a single `.html` file. No directories, no asset folders, no dependencies.
- The file must open in any modern browser with no internet connection. All JavaScript, CSS, and chart data are embedded inline.
- No external CDN calls. No iframes. No cookies. No tracking.
- The output aesthetic is formal and stakeholder-ready. No emojis. No casual language. Typography is clean and readable.

**Security and observability:** The project is continuously scanned by GitHub CodeQL (static analysis on every pull request) and OpenSSF Scorecard (automated security health scoring on every push to main). Pipeline progress is reported via structured events carrying per-stage elapsed time, enabling CI log analysis of generation bottlenecks in large repositories.

---

## Installation

Reveille requires Python 3.11 or later.

<details open>
<summary><strong>pip</strong></summary>

```bash
pip install reveille
```

</details>

<details>
<summary><strong>pipx (recommended for CLI tools)</strong></summary>

```bash
pipx install reveille
```

</details>

<details>
<summary><strong>uv</strong></summary>

Install permanently as a tool:

```bash
uv tool install reveille
```

Run without a permanent install:

```bash
uvx reveille generate --repo /path/to/repository
```

</details>

<details>
<summary><strong>Poetry (within a Poetry-managed project)</strong></summary>

```bash
poetry add reveille
```

</details>

**Verify the installation:**

```bash
reveille --version
```

---

## Quickstart

Navigate to any Git repository on your machine and run:

```bash
cd /path/to/your/repository
reveille generate
```

Reveille reads the local Git history and writes a report to the current directory. The output file is named `reveille-report.html` by default. Open it in any browser.

**Scaffold a configuration file before your first run:**

```bash
reveille init
```

This writes an annotated `reveille.toml` to the current directory with every available configuration key present and commented out. Edit only the keys you need. On all subsequent invocations, `reveille generate` will detect and load `reveille.toml` automatically — no `--config` flag required.

**Generate a report for a specific date range:**

```bash
reveille generate --since 2024-01-01 --until 2024-12-31
```

**Write the output to a specific path:**

```bash
reveille generate --output /tmp/q4-report.html
```

**Specify the repository path explicitly:**

```bash
reveille generate --repo /path/to/repository
```

---

## CLI Reference

### `reveille generate`

Generates the HTML performance report for the target repository.

| Flag | Short | Type | Default | Description |
|---|---|---|---|---|
| `--repo` | `-r` | `PATH` | `.` (current directory) | Path to the Git repository root. Must contain a `.git` directory. |
| `--output` | `-o` | `PATH` | `./reveille-report.html` | Path for the generated HTML file. Parent directories must exist. |
| `--since` | | `DATE` | Repository creation date | Include only commits on or after this date. Accepts `YYYY-MM-DD`. |
| `--until` | | `DATE` | Today | Include only commits on or before this date. Accepts `YYYY-MM-DD`. |
| `--branch` | `-b` | `TEXT` | The checked-out branch | Analyse commits reachable from this branch only. Defaults to whichever branch is currently checked out, which is not necessarily the repository's default branch. |
| `--exclude-author` | | `TEXT` | None | Exclude a contributor by name or email. Repeatable. |
| `--min-commits` | | `INT` | `1` | Exclude contributors with fewer than this many commits in the analysis window. |
| `--title` | | `TEXT` | Repository name | Override the report title displayed in the HTML output. |
| `--ranking` | | Flag | Off | Include the contributor ranking table. **Off by default** — it scores and tiers named individuals, which is more than the figures support. See [ADR 0010](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/adr/0010-ranking-is-opt-in.md). |
| `--no-ranking` | | Flag | Off | Explicitly omit the ranking table. Ranking is already off by default; this exists so existing invocations keep working. |
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
| `--mailmap` | | Flag | Off | Generate an annotated `.mailmap` template at the repository root alongside `reveille.toml`. Documents two-field, three-field, and four-field format variants with real-world examples. An existing `.mailmap` is silently skipped. |

### `reveille --version` / `-v`

Prints the installed version string and exits. This is a global flag rather than
a subcommand — `reveille version` is not a valid invocation.

```bash
reveille --version
```

### `reveille validate`

Validates that the target path is a readable Git repository and that the analysis window contains at least one commit. Exits with a non-zero status code if validation fails. Useful for CI integration.

```bash
reveille validate --repo /path/to/repository
```

`validate` also accepts `--verbose`, which emits diagnostic logging to stderr
without changing the exit code or the normal output.

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

## Output Description

The generated HTML file is structured as a formal report with the following sections.

**Repository Summary** — Name, remote URL if present, default branch, total commits in the analysis window, unique contributors, date range, and report generation timestamp.

**Activity Heatmap** — A GitHub-style year-navigable grid showing commit frequency by calendar day. Rows represent days of the week (Monday–Sunday); columns represent calendar weeks. Year tabs derived from the analysis window allow switching between calendar years without regenerating the report. A contributor dropdown provides per-contributor views alongside the aggregated default; single-contributor repositories hide the dropdown automatically.

**Commit Timeline** — A rolling area chart showing commit volume per calendar week over the analysis window. Highlights periods of high and low activity.

**Per-Contributor Commit Frequency** — A multi-trace line chart showing weekly commit frequency for each contributor individually across the analysis window. Each contributor is represented as a separate trace, enabling direct comparison of burst contributors versus those with sustained low-volume engagement — a distinction the aggregate timeline cannot convey.

**Contributor Summary Table** — A ranked table listing each contributor with their commit count, lines added, lines removed, net line delta, active days, most recent commit date, and assigned tier designation.

**Contribution Breakdown Charts** — Horizontal bar charts of commits and lines changed per contributor, and two donut charts showing each contributor's proportional share of total commits and total lines changed.

**Repository Activity Indicators** — Commit concentration (the minimum number of contributors accounting for 50% of commits) and longest inactive streak within the analysis window. Commit concentration is a measure of how concentrated the commit history is, not a bus factor: bus factor is a property of line ownership across the surviving codebase, which commit counts cannot establish. See the [User Guide](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md#repository-summary) for how to read it.

**JSON export** — When `--format json` is used, a structured JSON file is written at the same path stem as the HTML output. The payload contains repository metadata, ranked contributor statistics with all scoring fields, and derived health metrics. Suitable for dashboards, data warehouses, and CI integrations without parsing HTML.

**CSV export** — When `--format csv` is used, the ranked contributor table is written as a UTF-8 CSV file with BOM encoding. BOM ensures correct column rendering in Microsoft Excel on Windows without requiring a manual import wizard. Columns: rank, name, email, designation, tier, commits, lines added, lines deleted, net lines, active days, last commit date, composite score, percentile.

All charts are rendered with Plotly and are fully interactive — hover states, zoom, pan, and legend toggling are available without any external dependencies.

---

## Contributor Ranking System

Reveille assigns each contributor a tier designation based on a weighted composite of four metrics.

| Metric | Default Weight |
|---|---|
| Commit volume | 30% |
| Lines contributed (additions + deletions) | 25% |
| Activity consistency (active days / total days) | 25% |
| Recency (decay-weighted recent activity) | 20% |

Weights are configurable. See [Configuration](#configuration).

**These defaults are a documented judgement, not a derived model.** No study
establishes that these four signals in this proportion measure anything in
particular. Commit volume is weighted highest because it is the most robust of
the four — insensitive to file type and to how a change is split across lines.
Lines are weighted lower because a lockfile or a reformatting pass can dwarf
months of considered work. Recency is weighted lowest deliberately: recency is a
property of the analysis window rather than of the person, so weighting it higher
makes the same contributor's tier swing on the choice of end date.

**What this measures is the volume and regularity of commits — not
contribution, productivity, or value.** Both DORA and SPACE, the two most widely
cited bodies of research on software delivery measurement, state explicitly that
their metrics must not be used to assess individuals. Activity metrics are easy
to game and systematically misread review-heavy, mentoring, part-time, and
on-call work as low output. A contributor who spends a quarter unblocking others
and deleting a subsystem will rank below one who committed generated files.

Read a tier as a description of the shape of participation in one window, never
as a judgement about a person. If that framing does not fit your use, turn
ranking off with `--no-ranking` or `ranking.enabled = false`; the plain
contributor table remains.

The composite score maps to the following tier designations, applied relative to the contributor population in the analysis window.

| Tier | Designation | Composite Score Percentile |
|---|---|---|
| I | Private | 0 – 20th |
| II | Corporal | 21st – 40th |
| III | Sergeant | 41st – 60th |
| IV | Lieutenant | 61st – 75th |
| V | Captain | 76th – 88th |
| VI | Major | 89th – 95th |
| VII | Commander | 96th – 100th |

Tier boundaries and weights are documented defaults and are fully reproducible from the source. Changing the weights changes the scores but not the tier logic. Tiers are always relative to the contributor population within the analysis window, not absolute thresholds.

---

## Configuration

Reveille accepts a TOML configuration file for parameters that are cumbersome to pass on the command line on every invocation.

**Canonical workflow.** Run `reveille init` from your repository root to generate an annotated `reveille.toml`. Edit only the keys relevant to your analysis. From that point, `reveille generate` detects and loads `reveille.toml` automatically on every invocation — no flag required.

**Non-standard paths.** If the configuration file is named differently or stored outside the repository root, pass its path explicitly with `--config`. This is also the appropriate path for automation scripts that maintain multiple named configuration files for different analysis windows.

A fully commented `reveille.toml` is equivalent to no configuration file: all built-in defaults apply. A partially configured file applies only the keys present; absent keys fall back to defaults. A malformed file causes `reveille generate` to exit with a non-zero status, a parse error detail, and a remediation hint.

```toml
[report]
title = "Engineering Performance Report — Q4 2024"
output = "./reports/q4-2024.html"
branch = "main"
since = "2024-10-01"
until = "2024-12-31"
format = "html"

[filters]
min_commits = 2
exclude_authors = [
    "dependabot[bot]",
    "github-actions[bot]",
]

[ranking]
enabled = true
weights = { commits = 0.30, lines = 0.25, consistency = 0.25, recency = 0.20 }
```

CLI flags always take precedence over configuration file values. The configuration file is entirely optional — all values have defaults.

---

## Documentation

A full operational reference is available at [docs/USER_GUIDE.md](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/USER_GUIDE.md).
It covers every CLI flag and its interaction effects, every TOML key with
annotated examples, the ranking algorithm in plain language, how to interpret
each section of the generated report, and practical patterns for common use
cases.

For how Reveille is built rather than how it is used, see
[docs/ARCHITECTURE.md](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/ARCHITECTURE.md)
— the layering contract, the domain model, the analysis pipeline, and the
invariants the test suite protects. Individual design decisions and the
reasoning behind them are recorded in
[docs/adr/](https://github.com/varaprasadchilakanti/reveille/blob/main/docs/adr/).

The repository also carries an
[llms.txt](https://github.com/varaprasadchilakanti/reveille/blob/main/llms.txt)
index, which points a coding assistant at the right document and states the
handful of facts about Reveille that are easy to get wrong. `llms.txt` is a
proposed convention rather than a standard, and nothing depends on it.

---

## Development Setup

**Prerequisites:** Python 3.11 or later, `git`.

```bash
git clone git@github.com:varaprasadchilakanti/reveille.git
cd reveille
poetry install
```

**Verify the environment:**

```bash
poetry run reveille --version
poetry run mypy src/
poetry run ruff check src/
```

---

## Running Tests

```bash
pytest
```

**With coverage report:**

```bash
pytest --cov=reveille --cov-report=term-missing
```

**Type checking only:**

```bash
mypy src/
```

**Linting only:**

```bash
ruff check src/
```

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](https://github.com/varaprasadchilakanti/reveille/blob/main/CONTRIBUTING.md) before opening a pull request. It covers the development environment setup, architecture overview, pull request contract, code style requirements, and commit message conventions.

Participation is governed by the [Code of Conduct](https://github.com/varaprasadchilakanti/reveille/blob/main/CODE_OF_CONDUCT.md).

---

## Changelog

See [CHANGELOG.md](https://github.com/varaprasadchilakanti/reveille/blob/main/CHANGELOG.md) for the full release history. Reveille follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format and [Semantic Versioning 2.0](https://semver.org/).

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](https://github.com/varaprasadchilakanti/reveille/blob/main/CONTRIBUTING.md) before opening a pull request. It covers the development environment setup, architecture overview, pull request contract, code style requirements, and commit message conventions.

Pull requests carry two requirements beyond passing CI: each commit must be signed off (`git commit --signoff`), and the contributor-agreement box in the pull request template must be ticked. The agreement is [CLA.md](https://github.com/varaprasadchilakanti/reveille/blob/main/CLA.md); it opens with a plain-English explanation, and it does **not** transfer your copyright — you keep it, and you remain free to reuse your own code anywhere else. Filing issues and taking part in design discussions requires neither.

Participation is governed by the [Code of Conduct](https://github.com/varaprasadchilakanti/reveille/blob/main/CODE_OF_CONDUCT.md).

---
