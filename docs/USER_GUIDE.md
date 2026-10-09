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
- [What the Report Contains About People](#what-the-report-contains-about-people)
- [Before You Share a Report](#before-you-share-a-report)
- [The Ranking Algorithm](#the-ranking-algorithm)
- [Practical Patterns](#practical-patterns)
- [Troubleshooting and Questions](#troubleshooting-and-questions)

---

## How Reveille Works

When you run `reveille generate`, the tool performs the following steps
in sequence. Understanding this pipeline helps interpret the output and
diagnose unexpected results.

First, Reveille opens the target repository using GitPython and reads the
raw commit log for the specified branch and date range. Merge commits are
unconditionally excluded at this stage: a merge repeats work already counted
in the commits it joins, and counting it would credit whoever merged. A change
made only in a merge commit, such as a conflict resolution, is therefore not
counted either.

This is one `git log --numstat` read over the requested range rather than
one diff per commit, beside a `git rev-list` that authenticates each record
and a second `git log` that reads only `Co-authored-by` trailers. That is why
the read scales: on llama.cpp, 9,015
commits, the full JSON took 10 seconds and `reveille summary`, which skips the
line counts, 1.7 seconds. Reveille never changes the repository's Git data —
no commits, no branches, no configuration changes, no mutating Git command at
any point, and any output path inside `.git` is refused. It writes one file:
the report, at the path you give or `reveille-report.html` in the repository
root.

Second, raw commits are aggregated into per-contributor statistics. A
contributor's identity is keyed on their author email address, not their
display name. This means that a contributor who has committed under two
different names — common after a name change or when work and personal
accounts are mixed — is correctly treated as a single person, using the
name from their most recent commit. If a `.mailmap` file is present at
the repository root (in a bare repository, the `.mailmap` committed at
`HEAD`, as Git reads it), email aliases are resolved to their canonical
identity before aggregation. A contributor who has committed under
multiple email addresses is counted once, under the canonical identity
declared in `.mailmap`, rather than once per address.

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

Folding the noreply forms into each other is not the same as folding them
into your configured address. A commit made through the GitHub web
interface records the noreply address, so it still reads as a second
contributor until a `.mailmap` says otherwise — and the effect is easy to
miss, because a one-commit identity is a sliver in a chart and a full row
in the table.

Reveille's own [`.mailmap`](https://github.com/varaprasadchilakanti/reveille/blob/main/.mailmap)
is a worked example of exactly that case. `reveille init --mailmap`
generates an annotated template covering all four forms.

Third, only with `--ranking`, each listed contributor is scored using the
weighted composite algorithm and assigned a tier relative to the other
contributors in this analysis window. Tiers are not absolute — a contributor
ranked Captain in a ten-person team may rank Sergeant in a thirty-person team
analysed over a longer window.

Fourth, the Renderer assembles all data, computes derived metrics such as
commit concentration and the longest quiet run between commits, builds Plotly chart specifications,
and writes a single self-contained HTML file. All JavaScript and chart
data are embedded inline. The output file has no external dependencies and
can be opened in any modern browser without an internet connection.

---

## CLI Flags in Depth

### `--repo` / `-r`

The path to a Git repository: the root of a working tree, or a bare
repository. Defaults to the current working directory, which
means running `reveille generate` from inside a repository requires no
explicit flag. A bare repository needs `--output`: its root is Git's own
directory, where Reveille does not write.

```bash
reveille generate --repo /path/to/my-service
```

### `--output` / `-o`

The destination path for the generated HTML file. The parent directory
must exist — Reveille will not create intermediate directories. Defaults
to `reveille-report.html` placed at the repository root when no output
flag is provided, so by default the report is written into the working tree.
A path inside the Git directory, a path containing `..`, and a directory are
refused (exit 2). A path outside the repository given with `--output` is
written, with a warning on stderr; the same path set in `reveille.toml` is
refused, because a configuration file is found automatically and may come from
a repository you do not control.

```bash
reveille generate --output /tmp/reports/q4-2024.html
```

### `--since` and `--until`

Both flags accept dates in `YYYY-MM-DD` format. The `--since` boundary
is inclusive: commits on that calendar day are included. The `--until`
boundary is also inclusive. If neither is provided, the full commit
history on the target branch is analysed, up to today.

The window starts at the first commit, however early `--since` is: days
before a repository's first commit are not quiet days. Without `--until`,
a commit dated after today (a wrong clock, or a rebase that kept a future
date) is counted in no figure; the report header and a note on stderr say
how many, and `--until` with a later date includes them. With
`--deterministic` the window closes on the last commit instead, so nothing
is left out.

In a shallow clone, which CI checkouts are by default, only the history the
clone holds is analysed. The report header and a note on stderr say so; run
`git fetch --unshallow`, or check out with full depth, for the whole history.

```bash
reveille generate --since 2024-01-01 --until 2024-03-31
```

When `--since` is omitted but `--until` is provided, the window runs
from the repository's first commit up to the specified end date.
When `--until` is omitted but `--since` is provided, the window runs
from the later of the specified start date and the first commit up to
the current day (UTC).

### `--branch` / `-b`

Restricts analysis to commits reachable from the named branch. Defaults
to the repository's currently active branch. Use this flag when
generating a report scoped to a release branch or a long-running feature
branch.

```bash
reveille generate --branch release/2.0
```

### `--exclude-author`

Excludes a person by name or email address. The match is case-insensitive.
An identity is its address, so every commit made under an address that the
value matched anywhere in the branch's history (not only in the window) is
removed, whatever name it carries, as is every address a
`.mailmap` ties to it. A name that reaches more than one address removes all
of them, and stderr names the addresses so you can give one instead. A value
that matches nothing is reported on stderr. The flag is repeatable. See
[ADR 0020](adr/0020-exclude-author-removes-a-person-by-address.md).

```bash
reveille generate \
  --exclude-author "dependabot[bot]" \
  --exclude-author "github-actions[bot]" \
  --exclude-author "release-bot@example.com"
```

Accounts with `[bot]` in the name or address are already kept out of the
people figures (see [Summary cards](#summary-cards)); excluding one removes
its commits from every figure as well.

### `--min-commits`

Lists only contributors whose commit count within the analysis window is at
least this threshold. Defaults to `1`, meaning everyone is listed. It chooses
who is *listed*, not who is counted: every figure still describes everyone,
and the header says how many are listed
([ADR 0011](adr/0011-filters-choose-the-listing-not-the-analysis.md)). It is
not a privacy control.

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
contribution, not productivity, not value — and the SPACE framework says such
measures say little about a person: SPACE (Forsgren et al., 2021) holds that "developer
productivity is about more than an individual's activity levels". The caveats were always
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

### `--area-authors` and `--area-depth`

**Off by default.** `--area-authors` adds a section, *Who Changed Each Area*,
that lists the most-changed directories and, for each, how many commits changed
it, how many authors made them, who they are, and when it was last changed. It
names people, organised by directory rather than by person, so it is a separate
choice from `--ranking` and is not switched on by it. See
[ADR 0013](adr/0013-who-changes-what-is-opt-in-and-area-first.md).

```bash
reveille generate --area-authors
reveille generate --area-authors --area-depth 2
```

An area is a directory of at most `--area-depth` components (default 3, so
`src/app/core` rather than `src/app`); a file in a shallower directory belongs to
that directory, and files at the top level form the area `(root)`. Generated lock
files are left out. The eight areas with the most commits are shown.

Names are alphabetical, with no date or count beside any person; the one date
belongs to the area. When an area has more than five authors, the five shown are
those who changed it most recently, still alphabetical, and the line says so.
Identities whose name or address carries the `[bot]` suffix are listed on an
*Automated* line, by the same rule. An author
below `--min-commits` is counted and not named; an excluded author is neither.
The section says who changed each area, not who knows or owns it.

In `reveille.toml`:

```toml
[areas]
enabled = true
depth = 3
```

### A short answer: `reveille summary`

The repository in a few lines, naming no contributor: the window, commits,
people and automated accounts, the Gini, commit concentration, the longest
quiet run, days since the last commit, the written findings and the notice
that the figures need checking. It reads no line counts and no
`reveille.toml`. Takes `--repo`, `--since`, `--until`, `--branch`,
`--exclude-author`, `--deterministic` and `--format text|json`.

```bash
reveille summary
reveille summary --format json
```

It is the starting point for an assistant or a script: about 2 KB, and it
carries no contributor name or address. It does carry the repository and
branch names, which can name someone, and with one or two people its figures
describe identifiable individuals. Check it before sending it to a hosted
model.

### Who changed a file: `reveille who-changed`

A bug turns up in `src/parser/lexer.c`. Who should you ask?

```bash
reveille who-changed src/parser/lexer.c --since 2026-01-01
```

The answer names the path's authors alphabetically, the five who changed it
most recently (the people to ask first), automated accounts and co-authors
apart, and when the path was last changed. It gives no count or date for any
person: who changed a file is a fact the history records, while "who did the
most" is not what it is for. It reads only the commits that changed the path
and no line counts, so it answers in well under a second on a large history.
The path is taken literally and must be inside the repository.

### Output to stdout

`--output -` writes the report to stdout instead of a file, in any format, and
nothing else goes there: progress, notes and errors are on stderr. It is meant
for scripts and assistants that read the result directly.

```bash
reveille generate --format json --output - | jq .derived
```

CSV on stdout carries no byte-order mark; the BOM in a CSV file is there for
spreadsheet programs opening it.

### Co-authors

A commit made together credits its other authors with a `Co-authored-by:
Name <address>` trailer. Reveille reads those trailers (and nothing else in a
commit message) and reports them beside authorship, never inside it: each
contributor's co-authored count, a line naming identities credited only as
co-authors, and a finding with the number of commits that credit one. The
charts and every authorship figure count authors only. A trailer is written by
whoever wrote the commit and is not verified. See
[ADR 0014](adr/0014-co-authors-are-a-separate-fact.md).

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

Controls the output format for `reveille generate`. Accepts three values.

`html` is the default and produces the single self-contained HTML file at the path specified by `--output`.

`json` writes a structured JSON file at the same path stem as `--output` with a `.json` extension. The payload contains repository metadata, contributor statistics, and the derived summary measures; the scoring fields are present only with `--ranking`. The raw commits list is excluded. Suitable for consumption by dashboards and data warehouses without parsing HTML.

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
  "schema_version": "1.1",
  "metadata": { "name": "...", "analysed_branch": "main", "...": "..." },
  "provenance": {
    "reveille_version": "0.9.0",
    "head_sha": "…",
    "deterministic": false,
    "mailmap_applied": true,
    "commits_dated_after_window": 0,
    "shallow_clone": false,
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
  "derived": {
    "commit_concentration": 2,
    "gini_coefficient": 0.46,
    "population_size": 5,
    "contributors_below_threshold": 0,
    "...": "..."
  },
  "notice": "Computed from Git history by fixed rules, offline. History can be incomplete or wrong (rewritten, shallow, misdated, split identities); check before relying on it for a decision."
}
```

**`notice` travels with the figures.** It is the sentence printed under the HTML
report's header and with every `summary`, so a document passed on without the
page around it still says what it cannot carry.

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
file in the current directory, which must be the root of a repository; run
anywhere else, it stops with exit 2, even with `--output`. Every available configuration key is
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

`--force` applies to both generated files when `--mailmap` is set. Without it, an existing `.mailmap` is left alone and a message says so; with it, the existing file is overwritten by the template.

```bash
reveille init --mailmap
reveille init --mailmap --force
```

---

## TOML Configuration Reference

A TOML configuration file is useful when you run Reveille regularly
against the same repository with the same parameters. Pass its path with
`--config`, or name it `reveille.toml` in the directory you run Reveille
from, where it is loaded without being asked for. Use `reveille init` to
generate an annotated starting point.

A file loaded without `--config` is announced on stderr, with every setting
it applied, because the directory may belong to someone else. An output path
inside the repository's Git directory is refused with exit code 2, whether it
comes from the file or the command line.

The file is divided into four sections. All sections and all keys are
optional.

```toml
[report]
# Override the report title. Equivalent to --title.
title = "Repository Activity — Q4 2024"

# Output path for the HTML file. Equivalent to --output.
output = "./reports/q4-2024.html"

# Branch to analyse. Equivalent to --branch.
branch = "main"

# Analysis window start date. Equivalent to --since.
since = "2024-10-01"

# Analysis window end date. Equivalent to --until.
until = "2024-12-31"

# The most entries any list of people carries in JSON and CSV. Equivalent to --limit.
limit = 50

# Output format. Equivalent to --format.
# Accepted values: html (default), json, csv.
# format = "html"


[filters]
# Minimum commits to list a contributor. Equivalent to --min-commits.
min_commits = 2

# Authors to exclude by name or email. Equivalent to repeating --exclude-author.
exclude_authors = [
    "dependabot[bot]",
    "github-actions[bot]",
]


[ranking]
# Set to true to include the ranking table. Equivalent to --ranking.
# Off by default; read "The Ranking Algorithm" first.
enabled = false

# Metric weights for the composite score. All four values must sum to 1.0.
# The defaults shown here are the documented reproducible defaults.
weights = { commits = 0.30, lines = 0.25, consistency = 0.25, recency = 0.20 }


[areas]
# Set to true to add the "Who Changed Each Area" section, which names people.
# Equivalent to --area-authors. Off by default.
enabled = false

# Directory components that make an area. Equivalent to --area-depth.
depth = 3
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

The sections below are in the order the report shows them. Two of them,
**Who Changed Each Area** and **Contributor Rankings**, appear only when asked
for. For the order to read them in and what each supports, see
[PLAYBOOK.md](PLAYBOOK.md).

### Header and notice

The repository's name, its remote URL with any credential removed, the
analysed branch, the period and when the report was generated. When they
apply, lines state how many contributors are listed, how many commits are
dated after the window, how many could not be read, and that the repository
is a shallow clone. One
sentence under the header states the report's limits: the figures are
computed from Git history by fixed rules, offline, and history can be
incomplete or wrong, so check before relying on them for a decision.

### Summary cards

Total Commits, Contributors, Hold(s) Half the Commits, Longest Quiet Run
(days) and Distribution (Gini).

- **Total Commits** counts every non-merge commit in the window, after
  `--exclude-author`, including commits by automated accounts.
- **Contributors**, **Hold Half the Commits** and the **Gini** count people.
  An identity whose name or address carries `[bot]` is an automated account:
  it is counted in the commit and line totals, and listed in the table if it
  meets `--min-commits`, but not in these three figures, and a line under the cards says how many
  accounts and commits that left out. An automated account without the
  suffix is counted as a person; `--exclude-author` or a `.mailmap` deals with
  it. See [ADR 0017](adr/0017-distribution-figures-count-people.md).
- **Hold Half the Commits** is the fewest people whose commits together make
  at least half of the people's commits. A value of 1 means one person made
  most of them.
- **Longest Quiet Run** is the longest run of calendar days with no commit
  between two days that had one. The silence since the last commit is stated
  by a finding instead.
- `--min-commits` changes none of these: it chooses who is listed in the
  table, not who is counted ([ADR 0011](adr/0011-filters-choose-the-listing-not-the-analysis.md)).

**Hold Half the Commits is not a bus factor.** Bus factor asks how much of the
code still in the repository only one person understands, which needs
`git blame` across every file, not commit counts. Treat a low value as a
prompt to look at who owns which files, not as a measurement of that risk.

### What the History Shows

A few sentences, generated from the figures in the report by fixed rules,
without a language model: the same history always gives the same sentences.
They name nobody. With fewer than three people, a sentence that would in
effect describe one identifiable person, such as a share of commits or a
weekend-working pattern, is left out.

### Contribution Distribution

A Lorenz curve of how evenly commits are spread across the people in the
window, with the Gini coefficient as one number. The dotted diagonal is
perfect equality. The further the solid line bows beneath it, the more the
commits are concentrated.

**Read it as a description, not a score.**

- One person has a Gini of **0** by definition, and the curve is not drawn:
  there is no distribution to measure.
- One maintainer with many occasional contributors scores high for entirely
  ordinary reasons.
- The maximum for *n* people is `(n-1)/n`, never 1.0, so the value is
  comparable against this repository over time, not against another
  repository. The caption states the maximum for the report it is in.

### Commit Activity Heatmap

Commits per calendar day, one row per weekday and one column per week, over
the weeks of the window only. Days outside the window have no cell rather
than being drawn as days without commits. Year buttons switch between the
calendar years the window covers. A selector switches between the whole
repository and any one listed contributor. Where the grid is wider than the
screen, as on a phone, it opens on the latest week and says it scrolls
sideways. It needs JavaScript.

### Weekly Commit Timeline

Commits per calendar week across the window. Weeks with no commits are drawn
as zero. It needs JavaScript.

### Repository Profile

Six shares of the window, each from 0% to 100%, drawn as six separate petals
and listed in a table beside them on a wide screen, below on a narrow one.
It is plain HTML and SVG, so it renders without JavaScript and prints.

| Measure | The share of |
|---|---|
| Continuity | weeks in the window with at least one commit |
| Recent work | commits in the final quarter of the window |
| Shared | people's commits not made by the busiest person; automated accounts are left out |
| Collaboration | commits that credit a co-author |
| Revisiting | files touched by more than one commit; lock files are left out |
| Automation | commits by automated accounts |

**Expected by chance** is what evenly spread activity would give, computed
from each measure's own arithmetic where that is possible. It is not a target.
Collaboration, Revisiting and Automation have no such value and show a dash,
as does Shared when there are no people.
None of the six describes a person. See
[ADR 0016](adr/0016-the-profile-shape-returns-as-a-flower.md).

### Change Size per Commit

How many commits changed how many lines (added plus deleted), in buckets that
double in width: 0–9, 10–49, 50–199, 200–999, 1,000–4,999 and 5,000 or more.
The buckets widen, so the tallest bar is not the median; the median is marked.
It needs JavaScript.

### Where Change Concentrates

The twelve paths with the most lines changed (added plus deleted) in the
window, across everyone. A file that changes often is one to look at, not one
that is wrong. Lock files are left out, and the caption says how many and how
many lines. It needs JavaScript.

### Change by File Type

Lines changed per file extension: the eight largest, then the rest pooled as
"other", so the total is kept. Files without an extension, including
dotfiles, are one entry; so are lock files, whatever their extension. It
needs JavaScript.

### Per-Contributor Commit Frequency

Commits per week for up to four listed contributors, in the order of the
table, one line each, told apart by colour and by dash pattern. It is not
drawn with fewer than two. It needs JavaScript.

### Who Changed Each Area

Only with `--area-authors`. The eight most-changed directories, up to
`--area-depth` levels deep (default 3): how many commits changed each, how
many authors made them, when it was last changed, and the authors' names in
alphabetical order. No count or date is given per person; automated accounts
are listed apart; an author below `--min-commits` is counted but not named.
It says who changed an area, not who knows or owns it. See
[ADR 0013](adr/0013-who-changes-what-is-opt-in-and-area-first.md).

### Contributors

One row per listed contributor: name and email address, commits, lines added,
lines deleted, net lines, active days and the date of the last commit. Lines
count every file in each commit, generated files included, so they are a
volume signal, not a quality signal. Net lines is added minus deleted; a large
negative value is usually someone removing code. Active days is the number of
distinct dates with at least one commit. A long table scrolls inside its own
panel and prints in full. Identities credited only by a `Co-authored-by`
trailer are named beneath it; a trailer is not verified.

With `--ranking` this section is headed **Contributor Rankings** and adds a
rank, a tier and a composite score. Read
[The Ranking Algorithm](#the-ranking-algorithm) before turning it on.

### Contribution Breakdown

A donut of each contributor's share of all commits, and a bar chart of lines
added and deleted per listed contributor. Contributors beyond four, and anyone
`--min-commits` keeps out of the table, are pooled into one "Other
Contributors" slice, so the slices add up to every commit. It needs
JavaScript.

### Without JavaScript

The header, the cards, the written findings, the Repository Profile and the
contributor table are plain HTML. The other eight sections, which hold nine
charts, need JavaScript. Each
carries its figures in a table for screen readers, which is not shown on
screen, so with JavaScript off a sighted reader sees an empty panel.

## What the Report Contains About People

For each listed contributor, the HTML, JSON and CSV carry:

- the name and email address recorded in the commits;
- commits, lines added, lines deleted, net lines and active days;
- the date of the last commit (and, in JSON, of the first);
- how many commits credit the identity as a co-author.

With `--ranking`, each format adds a rank, a tier and a score per listed
contributor.

The HTML also carries, for each listed contributor, commits per day (the
heatmap's selector) and up to four contributors' commits per week
(Per-Contributor Commit Frequency), and file paths with their line counts
(Where Change Concentrates).

With `--area-authors`, the HTML names the authors of each of the eight
most-changed directories, and the JSON lists those directories with their
authors' names and addresses and the date each was last changed.

The HTML and JSON carry the repository's name, the analysed branch and its
remote URL, with any credential removed, and name the identities credited
only by a `Co-authored-by` trailer; the JSON gives their addresses and the
hash of the analysed commit. The CSV is the contributor table alone, with no
file paths; the JSON carries directory paths only with `--area-authors`.

`--exclude-author` values are recorded only as a count, never by name.
`reveille summary` names nobody. `reveille who-changed` names the authors of
one path, with their addresses.

Reveille sends none of this anywhere. The file goes where you write it, and
anyone who receives it receives all of the above. Given to a hosted AI
assistant, the JSON goes to that assistant's provider.

## Before You Share a Report

1. **Decide who needs it**, and send it only to them.
2. **Remove anyone who should not appear** with `--exclude-author`, which also
   matches every address a `.mailmap` ties to the value you give.
   `--min-commits` is **not** a privacy control: it hides rows, while their
   commits stay in every figure and can be worked out from them.
3. **Leave `--ranking` and `--area-authors` off** unless the question needs
   them. Both are off by default.
4. **For an assistant or a script, prefer `reveille summary`**, which names no
   contributor, or bound the JSON with `--limit`.
5. **Naming nobody is not anonymity.** With few people, a figure traces to one
   person; the repository name, branch, remote URL (an SSH login included),
   title and file paths can identify someone too. A report already sent is not
   changed by a later `--exclude-author`.
6. **Whether you may use a report about the people who work with you** is a
   question for the law and the agreements that apply to you.
   [COMPLIANCE.md](COMPLIANCE.md) sets out who is responsible for what. This
   guide is not legal advice.

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
volume. It counts lines of any kind, generated files included, so it says
how much text changed, not how much the change mattered.

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
the least easily distorted of the four: insensitive to file type, to generated
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
The SPACE framework (Forsgren et al., 2021) holds that "developer
productivity is about more than an individual's activity levels". DORA's metrics
are defined for applications and services, not people. Activity metrics are easy to game and
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

To keep a long table readable, list only contributors with at least ten
commits. Everyone is still counted in every figure, and the header says how
many are listed; commit count is not a measure of who did the most work.

```bash
reveille generate --min-commits 10 --title "Q3 Core Contributors"
```

### Adjusting Weights for a Maintenance Quarter

In a quarter dominated by bug fixes and refactoring rather than new
features, a team may prefer to weight consistency and recency above commit
volume. Adjusting the weights in `reveille.toml` changes the score; it does
not make it a measure of contribution.

```toml
[ranking]
weights = { commits = 0.15, lines = 0.15, consistency = 0.40, recency = 0.30 }
```

All four weights must sum to exactly 1.0. Reveille validates this at
startup and exits with an error if the constraint is violated.

### Exporting Machine-Readable Output for Downstream Integration

`--format json` produces a structured JSON file at the same path stem as the HTML output. The payload contains repository metadata, contributor statistics, and the derived summary measures — suitable for dashboards, data warehouses, and scripts without parsing HTML.

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

### Sharing a report

The HTML file is self-contained: the recipient needs only a browser, with
no server access or internet connection. It is about 4.9 MB, almost all of it
the embedded chart library, so its size barely depends on the repository:
4.90 MB for a one-commit repository and 4.92 MB for this one at 0.9.0.
Before sending it anywhere, read [Before You Share a Report](#before-you-share-a-report).

To share it through a wiki such as Confluence, attach the file to the page;
readers download it and open it locally. Pasting the file into an HTML macro
has not been tested by this project, and many sites disable that macro.

Whether a particular mail system accepts a 4.9 MB HTML attachment has not been
measured. If one refuses it, compress the file or share it through a file
store.

For a wider audience, a shared drive or an internal web server and a link
avoid attaching the file at all; it still names everyone listed in it.

## Troubleshooting and Questions

**Why does Reveille count fewer commits than `git log`?** Merge commits are
excluded. Without `--until` or `--deterministic`, commits dated after today
(UTC) are not counted;
the header and stderr say how many there were. `--exclude-author` removes an
author's commits from every figure.

**It says "No commits found" and exits 1.** No non-merge commit falls in the
window on the analysed branch. Check `--since`, `--until` and `--branch`; the
branch defaults to the one checked out.

**The report says the repository is a shallow clone.** Only the fetched
history was read, so every figure covers that part alone. `git fetch
--unshallow` fetches the rest.

**Someone who only merged branches is missing.** Merge commits are excluded,
so a person whose only commits are merges does not appear, and a change made
only in a merge, such as a conflict resolution, is not counted.

**The header says some commits were not read.** A commit whose author field
holds the characters Reveille separates records with cannot be read safely,
so it is left out and counted instead of being guessed at. Ordinary histories
have none; one that does was most likely written on purpose. See
[ADR 0019](adr/0019-how-history-is-read.md).

**It says the repository is a partial clone and exits 2.** A clone made with
`--filter` leaves some objects on the server, and reading them would make Git
fetch them. Reveille makes no network call and changes no Git data, so it
refuses. Run it on a clone made without `--filter`.

**`git log` shows history that the report leaves out, after a `git replace`.**
Reveille reads the objects the commit hashes name and does not follow replace
refs, grafts included, so the report and its recorded hash always describe the
same history. When any are present, the header and stderr say so. See [ADR
0018](adr/0018-replace-refs-are-not-honoured.md).

**One person appears twice.** Their commits carry two addresses. A `.mailmap`
at the repository root joins them (see
[How Reveille Works](#how-reveille-works) and `gitmailmap(5)`).
`reveille init --mailmap` writes an annotated template beside a new
`reveille.toml` and skips an existing `.mailmap`. If `reveille.toml` already
exists it stops (exit 2), and `--force` then replaces both files.

**A bot is counted as a person.** Only identities with `[bot]` in the name or
address are treated as automated. Exclude another with `--exclude-author`.

**The charts are empty.** Eight of the charts need JavaScript. The header,
cards, findings, Repository Profile and contributor table do not.

**Two runs over the same repository differ.** The end of the window and the
generation time come from the clock. `--deterministic` takes both from the
last commit, so an unchanged repository gives identical bytes.

**Is it safe to run on a repository someone sent me?** Git obeys a
repository's own `.git/config`, which can name a program for Git to run, and
Reveille runs Git. `git clone` does not copy that file; a copied directory or
an archive does. Run Reveille on a fresh clone of anything you do not trust.
See [SECURITY.md](../SECURITY.md).

**How do I uninstall it?** `pipx uninstall reveille`, `pip uninstall
reveille` or `uv tool uninstall reveille`, whichever installed it. Reveille
keeps no cache and no settings outside the files it was asked to write: the
reports, and any `reveille.toml` or `.mailmap` that `reveille init` created.
