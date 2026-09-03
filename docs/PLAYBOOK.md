# Playbook

How to read a Reveille report and act on it, in one page. Written for
whoever is holding the report — an engineering manager, a maintainer, or
an agent summarising it for someone else.

This page states *use*. It does not restate what the measures are; that
is [USER_GUIDE.md](USER_GUIDE.md), and the machine-readable version is
`reveille capabilities --format json`.

---

## Read it in this order

| # | Section | The question it answers |
|---|---|---|
| 1 | What the History Shows | What am I looking at, in five sentences? |
| 2 | Header figures | How much history, how many people, how recent? |
| 3 | Commit Activity Heatmap | When was work actually happening? |
| 4 | Weekly Commit Timeline | Is the pace steady, spiky, or stopped? |
| 5 | Contribution Distribution | Is this one person's repository or a team's? |
| 6 | Contributors | The same figures as text, per person. |

Stop at the first section that answers your question. The order is
deliberate: findings first, evidence after.

## What each measure supports, and what it does not

| Measure | Supports | Does **not** support |
|---|---|---|
| Commit count | How much recorded activity there was | How much work was done |
| Gini / Lorenz | Whether activity is concentrated | Whether that is a problem |
| Commit concentration | How few people hold most commits | A bus factor — it says nothing about who *knows* the code |
| Active days | Regularity of committing | Hours worked |
| Lines added/deleted | Size of recorded change | Quality, difficulty, or value |
| Weekend share | When commits were timestamped | Overwork — time zones and rebases move commits across the boundary |
| Ranking (`--ranking`) | Volume and regularity, nothing else | Any assessment of a person |

The ranking is off by default and should usually stay off. DORA and
SPACE both state that individual metrics of this kind must not be used
to assess people; [ADR 0010](adr/0010-ranking-is-opt-in.md) records why
this project agrees.

## Three questions it answers well

**"Is this project still alive?"**
`reveille generate --repo . --since 2025-01-01`. Read the timeline and
the dormancy finding. A flat tail is unambiguous; a quiet run is not —
released software commits rarely.

**"Are we down to one maintainer?"**
Read the distribution finding and the Lorenz curve. A high Gini with a
short contributor list is a staffing observation. It is not a bus
factor: someone may know the code without having committed recently.

**"What changed between two periods?"**
Run twice with different `--since`/`--until` and compare. Use
`--deterministic` so the only differences are real ones, and `--format
json` so a diff is meaningful.

## Three it answers badly

- **Comparing two repositories.** A Gini of 0.6 means different things
  in a library and a monorepo. These figures are comparable against the
  same repository over time.
- **Anything about an individual.** See the table above.
- **Anything about code quality.** Reveille reads history, never
  content. It cannot see a test, a review, or a defect.

## For agents and scripts

Read [llms.txt](../llms.txt) first — it is the short index. Then:

1. **Ask, do not guess:** `reveille capabilities --format json` reports
   the command surface, the guarantees, and the exit codes, read from
   the running program so they cannot drift from it.
2. **Branch on the exit code, not on stdout.** `0` affirmative, `1` ran
   correctly with a negative answer, `2` could not run.
3. **Check `schema_version` before parsing**, and carry `provenance`
   into whatever you produce — two reports that disagree are reconciled
   from it.
4. **Pass `--deterministic`** for anything cached, diffed, or compared.
5. **Never present a ranking as an assessment**, and never name an
   individual in a summary the default report does not name. The
   generated findings hold to this; anything built on top should too.

## Conventions this project holds to

These are the working rules, not aspirations. They are stated once here
and enforced elsewhere:

- **A guard that has not been observed to fail is not a guard.** Break
  the thing a new test protects, watch it fail, restore it.
- **An empty result from a tool that did not run is not evidence.**
  Check exit codes.
- **Execute the documentation; do not read it.** Every command on this
  page is run by the test suite.
- **One branch, one purpose.**

Full contributor detail is in [CONTRIBUTING.md](../CONTRIBUTING.md); the
design record is [ARCHITECTURE.md](ARCHITECTURE.md) and
[adr/](adr/).
