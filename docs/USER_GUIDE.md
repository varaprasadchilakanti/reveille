# Reveille — User Guide

This guide covers the full operational surface of Reveille. It assumes
you have already installed the tool and successfully run `reveille generate`
at least once. For installation instructions and a quickstart, refer to
the [README](../README.md).

---

## Contents

- [How Reveille Works](#how-reveille-works)
- [CLI Flags in Depth](#cli-flags-in-depth)
- [The reveille init Command](#the-reveille-init-command)
- [TOML Configuration Reference](#toml-configuration-reference)
- [Understanding the Report](#understanding-the-report)
- [The Ranking Algorithm](#the-ranking-algorithm)
- [Practical Patterns](#practical-patterns)

---

## How Reveille Works

When you run `reveille generate`, the tool performs the following steps
in sequence. Understanding this pipeline helps interpret the output and
diagnose unexpected results.

First, Reveille opens the target repository using GitPython and reads the
raw commit log for the specified branch and date range. Merge commits are
unconditionally excluded at this stage because they inflate both commit
counts and line change volumes without reflecting individual contributor
activity.

Second, raw commits are aggregated into per-contributor statistics. A
contributor's identity is keyed on their author email address, not their
display name. This means that a contributor who has committed under two
different names — common after a name change or when work and personal
accounts are mixed — is correctly treated as a single person, using the
name from their most recent commit. If a `.mailmap` file is present at
the repository root, email aliases are resolved to their canonical
identity before aggregation. A contributor who has committed under
multiple email addresses is unified under the canonical identity declared
in `.mailmap`, ensuring that ranking and contribution metrics reflect
actual individual output rather than the number of addresses used. The
four-field `.mailmap` form is not yet supported and is documented as a
known limitation.

Third, each contributor is scored using the weighted composite ranking
algorithm and assigned a tier designation relative to the other
contributors in this specific analysis window. Tiers are not absolute —
a contributor ranked Captain in a ten-person team may rank Sergeant in a
thirty-person team analysed over a longer window.

Fourth, the Renderer assembles all data, computes derived metrics such as
bus factor and longest inactive streak, builds Plotly chart specifications,
and writes a single self-contained HTML file. All JavaScript and chart
data are embedded inline. The output file has no external dependencies and
can be opened in any modern browser without an internet connection.

---

## CLI Flags in Depth

### `--repo` / `-r`

The path to the Git repository root. This must be a directory containing
a `.git` subdirectory. Defaults to the current working directory, which
means running `reveille generate` from inside a repository requires no
explicit flag.

```bash
reveille generate --repo /path/to/my-service
```

### `--output` / `-o`

The destination path for the generated HTML file. The parent directory
must exist — Reveille will not create intermediate directories. Defaults
to `reveille-report.html` placed at the repository root when no output
flag is provided.

```bash
reveille generate --output /tmp/reports/q4-2024.html
```

### `--since` and `--until`

Both flags accept dates in `YYYY-MM-DD` format. The `--since` boundary
is inclusive: commits on that calendar day are included. The `--until`
boundary is also inclusive. If neither is provided, the full commit
history on the target branch is analysed.

```bash
reveille generate --since 2024-01-01 --until 2024-03-31
```

When `--since` is omitted but `--until` is provided, the window runs
from the repository's first commit up to the specified end date.
When `--until` is omitted but `--since` is provided, the window runs
from the specified start date up to the current day.

### `--branch` / `-b`

Restricts analysis to commits reachable from the named branch. Defaults
to the repository's currently active branch. Use this flag when
generating a report scoped to a release branch or a long-running feature
branch.

```bash
reveille generate --branch release/2.0
```

### `--exclude-author`

Excludes a contributor by name or email address. The match is
case-insensitive. The flag is repeatable, so multiple authors can be
excluded in a single invocation.

```bash
reveille generate \
  --exclude-author "dependabot[bot]" \
  --exclude-author "github-actions[bot]" \
  --exclude-author "release-bot@example.com"
```

This flag is essential for repositories with active automation. Bot
commits inflate commit counts and active day metrics, which distorts both
the heatmap and the contributor rankings.

### `--min-commits`

Excludes contributors whose commit count within the analysis window falls
below the specified threshold. Defaults to `1`, meaning all contributors
with at least one commit are included. Setting this to `5` or `10` is
useful for retrospective reports where you want to surface sustained
contributors rather than one-off patches.

```bash
reveille generate --min-commits 5
```

### `--title`

Overrides the report title displayed in the HTML output. The default
title is the repository directory name. Use this flag to produce a report
with a human-readable or audience-specific heading.

```bash
reveille generate --title "Platform Engineering — Q1 2025 Retrospective"
```

### `--no-ranking`

Omits the contributor ranking table from the output entirely. The
heatmap, timeline, and contribution breakdown charts are still included.
This is appropriate when sharing a report with an audience where the
ranking context would be distracting or misinterpreted.

```bash
reveille generate --no-ranking
```


### `--config` / `-c`

Path to a TOML configuration file. CLI flags always take precedence over
values in the configuration file. See the [TOML Configuration Reference](#toml-configuration-reference)
for the full schema.

```bash
reveille generate --config ./reveille.toml
```

---

## The `reveille init` Command

`reveille init` scaffolds a fully annotated `reveille.toml` configuration
file in the current directory. Every available configuration key is
present, commented out, and accompanied by an inline description of its
purpose and accepted values. Run it once at the root of a repository
before your first `reveille generate` invocation to produce a starting
point you can edit rather than constructing the file from scratch.

```bash
reveille init
```

The generated file is identical in structure to the [TOML Configuration Reference](#toml-configuration-reference)
below. All keys are commented out by default, so the file has no effect
until you uncomment and edit the keys you need. CLI flags always take
precedence over values in the file, so you can override any setting on a
per-invocation basis without modifying it.

### `--output` / `-o`

Writes the configuration file to the specified path rather than
`reveille.toml` in the current directory. The parent directory must
exist.

```bash
reveille init --output /path/to/project/reveille.toml
```

### `--force`

Overwrites an existing configuration file at the target path without
prompting. Without this flag, `reveille init` exits with an error if the
file already exists, to prevent accidental data loss.

```bash
reveille init --force
```

---

## TOML Configuration Reference

A TOML configuration file is useful when you run Reveille regularly
against the same repository with the same parameters. Place it at the
repository root as `reveille.toml` or pass its path explicitly with
`--config`. Use `reveille init` to generate an annotated starting point.

The file is divided into three sections. All sections and all keys are
optional.

```toml
[report]
# Override the report title. Equivalent to --title.
title = "Engineering Performance Report — Q4 2024"

# Output path for the HTML file. Equivalent to --output.
output = "./reports/q4-2024.html"

# Branch to analyse. Equivalent to --branch.
branch = "main"

# Analysis window start date. Equivalent to --since.
since = "2024-10-01"

# Analysis window end date. Equivalent to --until.
until = "2024-12-31"


[filters]
# Minimum commits to include a contributor. Equivalent to --min-commits.
min_commits = 2

# Authors to exclude by name or email. Equivalent to repeating --exclude-author.
exclude_authors = [
    "dependabot[bot]",
    "github-actions[bot]",
]


[ranking]
# Set to false to omit the ranking table. Equivalent to --no-ranking.
enabled = true

# Metric weights for the composite score. All four values must sum to 1.0.
# The defaults shown here are the documented reproducible defaults.
weights = { commits = 0.30, lines = 0.25, consistency = 0.25, recency = 0.20 }
```

When a key is absent from the configuration file, the CLI default for
that parameter applies. When the same parameter is set in both the
configuration file and as a CLI flag, the CLI flag takes precedence.

---

## Understanding the Report

### Repository Summary

The summary cards at the top of the report provide four at-a-glance
metrics. Total commits and unique contributors reflect the analysis
window after all filters have been applied. Bus factor is the minimum
number of contributors whose combined commit volume accounts for at least
50 percent of total commits — a bus factor of 1 means a single person is
responsible for the majority of the codebase's history, which represents
a concentration risk. Max inactive days is the longest consecutive
calendar period within the analysis window on which no commits were
recorded.

### Activity Heatmap

The heatmap visualises when commits occurred across the analysis window as
a GitHub-style calendar grid. Rows represent days of the week
(Monday–Sunday); columns represent calendar weeks. Darker cells indicate
higher commit volumes. Empty cells — rendered as transparent — indicate
periods of no activity. Persistent gaps may indicate holidays, sprints
with no deliverables, or periods of reduced team capacity.

Year tabs above the chart allow switching between calendar years covered
by the analysis window without regenerating the report. The most recent
year is active by default. A contributor dropdown provides per-contributor
views alongside the aggregated default. In single-contributor repositories,
the dropdown is hidden automatically.

### Weekly Commit Timeline

This chart shows total commit volume per calendar week as a filled area
chart. It is useful for identifying sustained periods of high or low
activity, release sprints, and long-term trends in team output across the
analysis window.

### Contributor Rankings Table

Each row in the table represents one contributor. The columns are as
follows.

The rank number reflects the contributor's position by composite score
within this analysis window. It is not a permanent ranking — it changes
each time the window or weights are adjusted.

The designation is the tier label assigned based on the contributor's
percentile position within the population. See
[The Ranking Algorithm](#the-ranking-algorithm) for the full tier table
and the formula behind it.

Lines Added and Lines Deleted reflect the raw diff statistics from Git.
These numbers count all lines across all files in every commit and
include generated files, vendored dependencies, and documentation unless
those files were explicitly excluded from the repository's tracked
content. Interpret them as a volume signal, not a quality signal.

Net Lines is additions minus deletions. A large negative value indicates
a contributor who has been primarily removing code — refactoring, cleaning
up dead code, or reducing duplication — which is equally valuable work
but manifests differently in the metrics.

Active Days is the count of distinct calendar dates on which the
contributor made at least one commit. This is the raw input to the
consistency metric in the ranking calculation.

The Score bar and numeric value reflect the contributor's normalised
composite score in the range [0.0, 1.0]. Scores are relative to the
population — the top contributor always scores near 1.0 regardless of
absolute activity levels.

### Contribution Breakdown Charts

The two bar charts show commits and lines changed per contributor,
providing a visual complement to the table. The two donut charts show
each contributor's proportional share of total commits and total lines
changed. Contributors beyond eight are aggregated into a single
"Other Contributors" slice.

---

## The Ranking Algorithm

The ranking system assigns each contributor a composite score using four
normalised metrics. Understanding the algorithm helps interpret the tier
designations and informs decisions about adjusting the weights.

**Commit volume** measures the raw number of commits a contributor made
within the analysis window. Before scoring, this value is min-max
normalised across the contributor population, so the contributor with the
highest commit count receives a normalised value of 1.0 and the
contributor with the lowest receives 0.0.

**Lines contributed** measures the total lines changed (additions plus
deletions) across all commits. It is normalised in the same way as commit
volume. This metric rewards contributors who work on high-impact changes
but may commit less frequently.

**Activity consistency** is computed as the contributor's active days
divided by the total calendar days in the analysis window. A contributor
who commits on 60 of 90 days in a quarter receives a consistency score of
0.667. This metric is already bounded to [0.0, 1.0] and is not further
normalised. It rewards sustained engagement over the period rather than
concentrated bursts.

**Recency** uses an exponentially decayed commit frequency. Commits are
binned by ISO calendar week. The week containing the end of the analysis
window receives a weight of 1.0. Each prior week is multiplied by a decay
factor of 0.85 per week of distance. The score is the sum of commit count
multiplied by week weight across all weeks. This rewards contributors who
were recently active, ensuring that historical volume does not entirely
offset recent inactivity.

The four normalised scores are multiplied by their respective weights and
summed to produce the composite score. The default weights are commit
volume at 30 percent, lines contributed at 25 percent, consistency at 25
percent, and recency at 20 percent.

Each contributor's composite score is then converted to a percentile
rank within the population. The percentile determines the tier designation
according to the following table.

| Tier | Designation | Percentile Range |
|---|---|---|
| I | Private | 0th – 20th |
| II | Corporal | 21st – 40th |
| III | Sergeant | 41st – 60th |
| IV | Lieutenant | 61st – 75th |
| V | Captain | 76th – 88th |
| VI | Major | 89th – 95th |
| VII | Commander | 96th – 100th |

In a repository with a single contributor, that contributor receives the
Commander designation by definition, as their percentile is 100.0.

---

## Practical Patterns

### Scaffolding a Configuration File

Before committing to a set of parameters for a regularly-run report,
generate an annotated configuration file and edit only the keys you need.

```bash
reveille init
```

This writes `reveille.toml` to the current directory with every available
key present and commented out. Uncomment and set the keys relevant to
your repository, then run `reveille generate --config reveille.toml` on
subsequent invocations.

### Filtering Bot Authors

Repositories with active CI/CD pipelines, dependency update automation,
or release bots often have dozens or hundreds of commits attributed to
non-human authors. These inflate commit counts and active day metrics
across the board and should be excluded for any report intended as a
human contribution retrospective.

```bash
reveille generate \
  --exclude-author "dependabot[bot]" \
  --exclude-author "renovate[bot]" \
  --exclude-author "github-actions[bot]" \
  --exclude-author "semantic-release-bot"
```

Placing these exclusions in a `reveille.toml` at the repository root
avoids repeating them on every invocation.

```toml
[filters]
exclude_authors = [
    "dependabot[bot]",
    "renovate[bot]",
    "github-actions[bot]",
    "semantic-release-bot",
]
```

### Scoping to a Release Branch

When generating a retrospective for a specific release cycle, restrict
the analysis to the branch and date range that correspond to that
cycle.

```bash
reveille generate \
  --branch release/3.0 \
  --since 2024-09-01 \
  --until 2024-11-30 \
  --title "Release 3.0 — Engineering Retrospective"
```

### Surfacing Sustained Contributors

For a report intended for an engineering director or a quarterly business
review, filtering out contributors with very few commits focuses the
output on the people who drove the majority of the work.

```bash
reveille generate --min-commits 10 --title "Q3 Core Contributors"
```

### Adjusting Weights for a Maintenance Quarter

In a quarter dominated by bug fixes and refactoring rather than new
features, commit volume is a less representative signal than consistency
and recency. Adjusting the weights in `reveille.toml` produces a ranking
that better reflects the actual nature of the work.

```toml
[ranking]
weights = { commits = 0.15, lines = 0.15, consistency = 0.40, recency = 0.30 }
```

All four weights must sum to exactly 1.0. Reveille validates this at
startup and exits with an error if the constraint is violated.

### Embedding in Confluence

The generated HTML file is self-contained and opens correctly in any
modern browser. To embed it in Confluence, use the HTML Macro on the
target page, paste the full content of the generated file into the macro
body, and save. All charts and styling will render without modification.

Alternatively, attach the HTML file directly to the Confluence page as
a file attachment. Readers can download and open it locally.

### Sharing over Email

Because the output is a single file with no external dependencies, it can
be attached to an email and opened by the recipient without any additional
tooling, server access, or internet connection.

For distribution to a broader audience, consider placing the file on an
internal web server or a shared drive and sharing a link rather than
attaching the full file, as the embedded Plotly bundle means the file
size is typically between 3.5 MB and 5 MB depending on the number of
charts and contributors.
