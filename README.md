# Reveille

**A CLI tool that generates self-contained HTML performance reports from local Git repositories.**

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

- Contribution heatmaps showing commit activity across four granularity levels: per calendar day, per calendar week, per calendar month, and per calendar year — switchable in the rendered report without regeneration
- Commit frequency timelines and rolling activity charts
- Per-contributor breakdowns covering commits, lines added and removed, and active day counts
- A structured ranking table assigning each contributor a tier designation based on weighted activity metrics
- Repository health indicators including bus factor, longest inactive streak, and consistency scores

**Design constraints that are non-negotiable:**

- The output is always a single `.html` file. No directories, no asset folders, no dependencies.
- The file must open in any modern browser with no internet connection. All JavaScript, CSS, and chart data are embedded inline.
- No external CDN calls. No iframes. No cookies. No tracking.
- The output aesthetic is formal and stakeholder-ready. No emojis. No casual language. Typography is clean and readable.

---

## Installation

Reveille requires Python 3.11 or later.

**Install from PyPI:**

```bash
pip install reveille
```

**Install with pipx (recommended for CLI tools):**

```bash
pipx install reveille
```

**Install with Poetry (within a Poetry-managed project):**

```bash
poetry add reveille
```

**Install with uv:**

```bash
uv tool install reveille
```

**Run without a permanent install (uv):**

```bash
uvx reveille generate --repo /path/to/repository
```

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
| `--branch` | `-b` | `TEXT` | Default branch | Analyse commits reachable from this branch only. |
| `--exclude-author` | | `TEXT` | None | Exclude a contributor by name or email. Repeatable. |
| `--min-commits` | | `INT` | `1` | Exclude contributors with fewer than this many commits in the analysis window. |
| `--title` | | `TEXT` | Repository name | Override the report title displayed in the HTML output. |
| `--no-ranking` | | Flag | Off | Omit the contributor ranking table from the output. |
| `--heatmap-granularity` | | `TEXT` | `monthly` | Default heatmap view on open. Accepted values: `daily`, `weekly`, `monthly`, `yearly`. All four views are available via toggle buttons in the rendered report regardless of this setting. |
| `--config` | `-c` | `PATH` | None | Path to a TOML configuration file. If omitted, `reveille.toml` in the current working directory is loaded automatically when present. Use this flag for non-standard file names or paths outside the repository root. CLI flags always take precedence over configuration file values. |

### `reveille init`

Scaffolds a fully annotated `reveille.toml` configuration file in the current directory. Every available key is present, commented out, and documented inline. Run this once before your first `reveille generate` invocation to produce a starting point you can edit rather than constructing the file from scratch.

| Flag | Short | Type | Default | Description |
|---|---|---|---|---|
| `--output` | `-o` | `PATH` | `./reveille.toml` | Destination path for the generated configuration file. |
| `--force` | | Flag | Off | Overwrite an existing file at the target path without prompting. |

### `reveille version`

Prints the installed version string and exits.

### `reveille validate`

Validates that the target path is a readable Git repository and that the analysis window contains at least one commit. Exits with a non-zero status code if validation fails. Useful for CI integration.

```bash
reveille validate --repo /path/to/repository
```

### `reveille help`

Displays the top-level help text listing all available commands and global options. Equivalent to `reveille --help`.

```bash
reveille help
```

---

## Output Description

The generated HTML file is structured as a formal report with the following sections.

**Repository Summary** — Name, remote URL if present, default branch, total commits in the analysis window, unique contributors, date range, and report generation timestamp.

**Activity Heatmap** — A calendar-style matrix showing commit frequency across the analysis window. Four granularity views are available via toggle buttons in the rendered report: `daily` shows one cell per calendar day in a GitHub-style grid capped at a rolling 365-day window; `weekly` and `monthly` aggregate by day-of-week across each week or month; `yearly` aggregates by month across each calendar year. The `--heatmap-granularity` flag controls which view is active on first open.

**Commit Timeline** — A rolling area chart showing commit volume per calendar week over the analysis window. Highlights periods of high and low activity.

**Contributor Summary Table** — A ranked table listing each contributor with their commit count, lines added, lines removed, net line delta, active days, most recent commit date, and assigned tier designation.

**Contribution Breakdown Charts** — Horizontal bar charts of commits and lines changed per contributor, and two donut charts showing each contributor's proportional share of total commits and total lines changed.

**Repository Health Indicators** — Bus factor estimate (minimum number of contributors accounting for 50% of commits) and longest inactive streak within the analysis window.

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
# Accepted values: "daily", "weekly", "monthly", "yearly"
heatmap_granularity = "monthly"

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

Contributions are welcome. Before opening a pull request, please read the following.

**Reporting issues.** Use GitHub Issues. Include the output of `reveille --version`, the operating system, Python version, and a minimal reproduction case. If the issue involves a specific repository, a sanitised `git log --oneline` covering the relevant range is sufficient — do not include source code.

**Proposing changes.** Open an issue before starting significant work. This avoids duplication and ensures the direction is aligned before effort is invested.

**Submitting pull requests.** All pull requests must target the `main` branch. The CI pipeline runs `ruff`, `mypy`, and `pytest` on every pull request. All three must pass. New public functions require docstrings. New behaviour requires tests. The output contract — single self-contained HTML file, no external calls, formal aesthetic — is non-negotiable and must be preserved in every contribution.

**Code style.** Ruff handles linting and import ordering. Mypy runs in strict mode. Type annotations are required on every function signature. Early returns are preferred over nested conditionals throughout.

**Commit messages.** Follow the Conventional Commits specification: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. Scope is optional but encouraged, e.g. `feat(ranking): add recency decay weighting`.

---

## Changelog

See [CHANGELOG.md](https://github.com/varaprasadchilakanti/reveille/blob/main/CHANGELOG.md) for the full release history. Reveille follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format and [Semantic Versioning 2.0](https://semver.org/).

---

## Licence

Reveille is released under the [MIT Licence](https://github.com/varaprasadchilakanti/reveille/blob/main/LICENSE).
