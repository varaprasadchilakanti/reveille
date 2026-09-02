# Reveille — User Guide

This guide covers the full operational surface of Reveille. It assumes
you have already installed the tool and successfully run `reveille generate`
at least once. For installation instructions and a quickstart, refer to
the [README](../README.md).

---

## Contents

- [How Reveille Works](#how-reveille-works)
- [CLI Flags in Depth](#cli-flags-in-depth)
- [Exit Codes](#exit-codes)
- [The reveille capabilities Command](#the-reveille-capabilities-command)
- [Structured Output](#structured-output)
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

This is a single `git log --numstat` pass over the requested range,
which is why the read scales to large repositories: it costs roughly
0.8 milliseconds per commit, so a 50,000-commit history is read in
under a minute rather than the several minutes a per-commit diff would
take. Reveille never writes to the repository — no commits, no
branches, no configuration changes, no mutating Git command at any
point. The only file it writes is the output file you name.

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
actual individual output rather than the number of addresses used.

All four `.mailmap` forms defined by `gitmailmap(5)` are supported, and
matching follows Git's own precedence: the most specific rule wins.
A rule naming both a name and an email is tried first, then one naming
an email alone, then one naming a name alone. Matching is
case-insensitive, and malformed lines are skipped silently — again
matching Git's behaviour, so a `.mailmap` that works with `git shortlog`
works here.

GitHub noreply addresses are folded automatically, with no `.mailmap`
entry required. The legacy `username@users.noreply.github.com` and the
post-2017 `12345678+username@users.noreply.github.com` forms both exist,
and the same person frequently appears under both; the numeric prefix is
stripped so the two collapse into one contributor.

Third, each contributor is scored using the weighted composite ranking
algorithm and assigned a tier designation relative to the other
contributors in this specific analysis window. Tiers are not absolute —
a contributor ranked Captain in a ten-person team may rank Sergeant in a
thirty-person team analysed over a longer window.

Fourth, the Renderer assembles all data, computes derived metrics such as
commit concentration and longest inactive streak, builds Plotly chart specifications,
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

### `--ranking` and `--no-ranking`

**The contributor ranking is off by default from v0.8.0.** `--ranking` turns it
on. `--no-ranking` still works and is still honoured; if both are given,
`--no-ranking` wins, because between two contradictory instructions the one that
produces less is the safer reading.

```bash
reveille generate --ranking
```

With ranking off — the default — the report omits the scored contributor table,
and the JSON omits `tier`, `tier_designation`, `composite_score` and `percentile`
entirely rather than emitting them with placeholder values. A key reading
`"tier": 0` is a number a consumer can mistake for data; an absent key cannot be.
Check `provenance.ranking.enabled` to know which shape you have.

Everything else stays: the contributor table with commits, lines and active days,
the activity heatmap, the timelines, and the distribution chart.

**Why it is off.** The ranking assigns named individuals a composite score, a
percentile and a tier designation, weighted 30% commits and 25% lines changed.
Those figures measure the volume and regularity of commits and nothing else — not
contribution, not productivity, not value — and both DORA and SPACE state that
such measures must not be used to assess individuals. The caveats were always
documented, but documentation does not travel with the artefact: the HTML report
is built to be forwarded, and the caveats stay in this repository. See
[ADR 0010](adr/0010-ranking-is-opt-in.md).

It is a legitimate thing to look at deliberately, for your own repository, having
read what it does and does not mean. That is what the flag is for.

You can also set it in `reveille.toml`:

```toml
[ranking]
enabled = true
```

It must be a real boolean. `enabled = "false"` is a *string*, and would be
rejected rather than quietly read as true.

### `--deterministic`

Produces byte-reproducible output: two runs over an unchanged repository give
identical bytes, in every format.

```bash
reveille generate --deterministic
```

It does two things. It pins `generated_at` to the timestamp of the analysed
commit rather than to the clock — the same idea as `SOURCE_DATE_EPOCH` in a
reproducible build. And it closes the analysis window on the last commit rather
than on today.

**That second part changes the numbers, not only the bytes.** The ranking's
recency component is measured against the window, so pinning the window pins the
scores. Without it, two runs over an identical repository on different days would
differ, and the output would not be reproducible in any useful sense. This is why
the flag is opt-in, and why `provenance.deterministic` records that it was used —
a deterministic report is never silently comparable with a normal one.

Use it when a report needs to be re-checkable: attached to an audit, committed
alongside a release, or compared against an earlier run to see what changed.

### `--config` / `-c`

Path to a TOML configuration file. CLI flags always take precedence over
values in the configuration file. See the [TOML Configuration Reference](#toml-configuration-reference)
for the full schema.

```bash
reveille generate --config ./reveille.toml
```

### `--format`

Controls the output format for `reveille generate`. Accepts four values.

`html` is the default and produces the single self-contained HTML file at the path specified by `--output`.

`json` writes a structured JSON file at the same path stem as `--output` with a `.json` extension. The payload contains repository metadata, ranked contributor statistics with all scoring fields, and derived health metrics. The raw commits list is excluded. Suitable for consumption by dashboards and data warehouses without parsing HTML.

`csv` writes the ranked contributor table as a UTF-8 CSV file with BOM encoding at the same path stem as `--output` with a `.csv` extension. BOM ensures correct column rendering in Microsoft Excel on Windows without requiring a manual import wizard configuration.

```bash
reveille generate --format json --output /tmp/reports/q4.html
reveille generate --format csv --output /tmp/reports/q4.html
```

---

## Exit Codes

Every command returns one of three codes. They are a supported contract:
the numbers will not change without a major version bump.

| Code | Meaning | When |
|---|---|---|
| `0` | Success | The command ran and its answer is affirmative. |
| `1` | Negative answer | Reveille ran correctly and the repository state does not satisfy the request. The analysis window contains no commits, or the repository has no commits at all. |
| `2` | Could not run | Reveille could not perform the request. Invalid flag value, malformed configuration, a path that is not a readable Git repository, or an output location that cannot be written. |

**The distinction between `1` and `2` is the one worth scripting against.** A
negative answer may be an acceptable state to record — a newly created repository
legitimately has nothing to report. An inability to run is a broken pipeline step
and usually means a misconfiguration.

```bash
reveille validate --repo ./service
case $? in
  0) echo "has commits, proceeding" ;;
  1) echo "no commits in range - skipping report" ;;
  2) echo "misconfigured, failing the build" >&2; exit 1 ;;
esac
```

Diagnostic detail beyond this three-way split is written to stderr, not encoded
in the exit code. Adding a distinct code per cause does not scale: the range is
small, and every new cause would break scripts branching on the old numbering.

### Diagnostics

Pass `--verbose` to `generate` or `validate` to write DEBUG-level diagnostics to
stderr. Normal output is unchanged, so adding the flag is safe in an existing
pipeline. It reports the fully resolved configuration after CLI flags and the
TOML file have been merged, the exact `git log` invocation used, how many commits
were read, and every file written — which is usually enough to explain an
unexpected report without a debugger.

```bash
reveille generate --verbose 2> reveille-debug.log
```

Reveille's modules log through the standard `logging` module under the `reveille`
logger and install no handler of their own. Importing Reveille as a library is
therefore silent unless the host application configures logging itself.

---

## The `reveille capabilities` Command

Describes what Reveille can and cannot do, for a person or for a program.

```bash
reveille capabilities              # readable text
reveille capabilities --format json
```

The JSON form is the one worth knowing about if you are wiring Reveille into a
script or handing it to an agent. It carries `capabilities_version`, the tool
version, the output schema version, the guarantees that hold on every run, a
`can` list, a `cannot` list where each entry says what to use instead, the
caveats that change how a number should be read, every command with its options,
and the exit-code contract.

The command surface and the exit codes are **read from the running program**
rather than restated, so they cannot drift from it. The judgements — what the
tool is for and what it refuses to claim — are written once and tested for
completeness.

The `cannot` list is the half worth reading. It states that Reveille does not
measure productivity or contribution value, is not fit for performance review or
hiring decisions, does not compute a bus factor, reads no source code, and does
not aggregate a person across repositories.

## Structured Output

`--format json` emits a document whose first key is `schema_version`, so a
consumer can decide whether it can parse the rest before trying.

```json
{
  "schema_version": "1.0",
  "metadata": { "name": "...", "analysed_branch": "main", "...": "..." },
  "provenance": {
    "reveille_version": "0.8.0",
    "head_sha": "…",
    "deterministic": false,
    "mailmap_applied": true,
    "filters": {
      "requested_branch": "main",
      "requested_since": null,
      "requested_until": null,
      "exclude_authors_count": 0,
      "min_commits": 1
    },
    "ranking": { "enabled": false, "weights": null }
  },
  "contributors": [ "..." ],
  "derived": { "commit_concentration": 2, "gini_coefficient": 0.46, "...": "..." }
}
```

**`schema_version` changes when the shape changes**, not when the tool does.
A major bump means a removal or a rename; a minor bump means a purely additive
field. v0.7.0 renamed a key with no way for a consumer to detect it except a
`KeyError` at runtime, which is why this field exists.

**`provenance` records what produced the numbers**, so two reports that disagree
can be reconciled. Note the distinction between `metadata.analysis_since` (where
the window began) and `provenance.filters.requested_since` (whether anybody asked
for it) — without both, "the full history, which starts in March" and "filtered
to start in March" are the same document.

`exclude_authors_count` is a count rather than the values. `--exclude-author`
exists to keep somebody out of the report, so recording their address here would
put it back.

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

### `--mailmap`

Generates a fully annotated `.mailmap` template at the repository root alongside `reveille.toml`. The template documents all four forms defined by `gitmailmap(5)` — name correction, email alias to canonical identity, email-only remapping, and the four-field form that disentangles several people sharing one address — each with concrete examples covering employer domain changes, GitHub noreply addresses, name corrections, and shared build-machine accounts. It also documents the matching precedence, so a rule that does not fire can be diagnosed from the template itself.

`--force` applies to both generated files when `--mailmap` is set. If a `.mailmap` file already exists, it is silently skipped — `.mailmap` is a Git-native file and its presence is not treated as a conflict.

```bash
reveille init --mailmap
reveille init --mailmap --force
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

# Output format. Equivalent to --format.
# Accepted values: html (default), json, csv.
# format = "html"


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

### `[report] deterministic`

```toml
[report]
deterministic = true
```

Equivalent to `--deterministic`. Must be a real boolean; a quoted `"false"` is a
string and is rejected rather than read as true.

## Understanding the Report

### Repository Summary

The summary cards at the top of the report provide four at-a-glance
metrics. Total commits and unique contributors reflect the analysis
window after all filters have been applied. Commit concentration is the
minimum number of contributors whose combined commit volume accounts for
at least 50 percent of total commits — a value of 1 means a single person
authored the majority of the history in the analysis window. Max inactive
days is the longest consecutive calendar period within the analysis window
on which no commits were recorded.

**Commit concentration is not a bus factor, and should not be read as one.**
Bus factor asks how much of the surviving code only one person understands.
That is a property of line ownership — who wrote the code that is still in
the repository today — and answering it requires `git blame` across every
file, not commit counts. Commit volume is a weak proxy: a contributor who
makes many small commits outranks one who wrote an entire subsystem in a
handful of large ones, and a contributor whose work has since been rewritten
still counts in full. Treat a low value as a prompt to look at who owns which
files, not as a measurement of that risk. Reveille reports this metric under
a name that describes what it actually computes; before v0.7.0 it was
labelled "bus factor", which overstated it.

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

### Contribution Distribution

A Lorenz curve of how evenly commits are spread across contributors, with the
Gini coefficient as a single-number summary. The dotted diagonal is perfect
equality — every contributor with the same number of commits. The further the
solid line bows beneath it, the more activity is concentrated in fewer people.

**Read it as a description, not a score.** A high value is not a fault and a low
one is not a target:

- A single-maintainer repository has a Gini of **0** by definition. Equality is
  trivially true in a population of one, which is the opposite of the intuitive
  reading.
- A project with one maintainer and many occasional contributors scores high for
  entirely ordinary reasons.
- The maximum for a sample of *n* contributors is `(n-1)/n`, never 1.0 — one
  person holding everything among four gives 0.75. The ceiling rises with the
  contributor count, so **the value is comparable against this repository over
  time, not against a different repository.**

Both instruments are borrowed rather than invented: the Lorenz curve (1905) and
the Gini coefficient (1912) are the standard measures of concentration in a
population, and a century of interpretation — and of documented weakness — comes
with them. They replaced an ad-hoc "how many contributors make up a majority"
count that had no defined range and jumped whenever somebody crossed half.

Unlike the ranking, this names nobody, and the curve is unchanged by who sits
where in it. That is why it stays in the default report.

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

**Why those numbers.** They are a documented judgement, not a derived
model — no study establishes that these four signals in this proportion
measure anything in particular. Commit volume is highest because it is
the most robust of the four: insensitive to file type, to generated
code, and to how a change happens to be split across lines. Lines are
lower because they are the easiest to distort — a vendored dependency, a
lockfile, or a reformatting pass can dwarf months of considered work.
Consistency rewards sustained participation over a single burst. Recency
is lowest deliberately, because recency is a property of the analysis
window rather than of the person; weight it higher and the same
contributor's tier swings on the choice of end date.

They are configurable precisely because they are a judgement. If the
defaults do not describe what you are trying to see, change them — see
[Adjusting Weights for a Maintenance Quarter](#adjusting-weights-for-a-maintenance-quarter).

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

Tied composite scores receive identical percentiles, and therefore
identical tiers. Percentile is a lower-bound rank, so a tied group sits
at the bottom of its band rather than being ordered arbitrarily.

In a repository with a single contributor, that contributor receives the
Commander designation by definition, as their percentile is 100.0.

### What the ranking does not measure

The ranking measures the volume and regularity of commits, because that
is what Git records. It does not measure contribution, productivity, or
value, and it should not be used to assess an individual.

This is the stated position of the research rather than a disclaimer.
Both DORA and SPACE — the two most widely cited bodies of work on
software delivery measurement — say explicitly that their metrics must
not be applied to individuals. Activity metrics are easy to game and
systematically misread review-heavy, mentoring, part-time, and on-call
work as low output. A contributor who spends a quarter unblocking
colleagues and deleting a subsystem will rank below one who committed
generated files.

Read a tier as a description of the shape of participation in one
window. It is not a statement about a person, and the military
designations are a visual device, not a rank.

If that framing does not fit your use, turn ranking off entirely with
`--no-ranking` or `ranking.enabled = false`. The contributor table,
heatmap, timelines, and breakdown charts all remain; only the scores,
percentiles, and tiers are dropped.

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

### Exporting Machine-Readable Output for Downstream Integration

`--format json` produces a structured JSON file at the same path stem as the HTML output. The payload contains repository metadata, ranked contributor statistics, and derived health metrics — suitable for dashboards, data warehouses, and Jira integrations without parsing HTML.

```bash
reveille generate --format json --output /tmp/reports/q4.html
```

The JSON file is written to `/tmp/reports/q4.json`.

### Exporting the Contributor Table to a Spreadsheet

`--format csv` produces the ranked contributor table as a UTF-8 CSV file with BOM encoding, for direct import into Microsoft Excel, Google Sheets, or any spreadsheet application.

```bash
reveille generate --format csv --output /tmp/reports/q4.html
```

The CSV file is written to `/tmp/reports/q4.csv`.

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
