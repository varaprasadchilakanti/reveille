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
| 1 | Header, notice and cards | How much history, how many people, how recent? |
| 2 | What the History Shows | What am I looking at, in a few sentences? |
| 3 | Contribution Distribution | Is this one person's repository or a team's? |
| 4 | Commit Activity Heatmap | When was work actually happening? |
| 5 | Weekly Commit Timeline | Is the pace steady, spiky, or stopped? |
| 6 | Repository Profile | What shape does the work have, against what chance would give? |
| 7 | Change Size, Where Change Concentrates, Change by File Type | How big are changes, where do they land, and what kind of work is it? |
| 8 | Contributors | The figures per person, as text. |

This is the order the report shows them in. What each section contains is in
[USER_GUIDE.md](USER_GUIDE.md#understanding-the-report).

Stop at the first section that answers your question. The order is
deliberate: findings first, evidence after.

## What each measure supports, and what it does not

| Measure | Supports | Does **not** support |
|---|---|---|
| Commit count | How much recorded activity there was | How much work was done |
| Contributors, Gini, Hold Half | How activity is spread across people; automated accounts with `[bot]` are stated apart | How many people work on the code: review, pairing and unmerged work leave no commit |
| Gini / Lorenz | Whether activity is concentrated | Whether that is a problem |
| Commit concentration | How few people hold most commits | A bus factor — it says nothing about who *knows* the code |
| Active days | Regularity of committing | Hours worked |
| Lines added/deleted | Size of recorded change | Quality, difficulty, or value |
| Weekend share | When commits were timestamped | Overwork — time zones and rebases move commits across the boundary |
| Ranking (`--ranking`) | Volume and regularity, nothing else | Any assessment of a person |

The ranking is off by default and should usually stay off. The SPACE
framework says activity counts should never be used on their own to
reward or penalise developers; [ADR 0010](adr/0010-ranking-is-opt-in.md) records why
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

## For an audit or due diligence

1. **Make the run repeatable.** `--deterministic` takes the end of the window
   and the generation time from the last commit, so the same repository gives
   the same bytes. Keep the JSON: `provenance` records the Reveille version,
   the analysed commit hash, whether a `.mailmap` was applied, whether the
   clone was shallow, and the filters as requested.
2. **Reconcile before relying.** `total_commits` should match
   `git rev-list --no-merges --count <commit>` over the same window; merge
   commits are excluded by design.
3. **Know what it is not evidence of.** Author names and addresses are
   whatever the committer's Git was set to; Reveille does not verify them,
   and it does not read who reviewed, approved or merged a change. Commit
   history shows that changes were made, not that they were authorised.

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

## Where the measures come from

None of these is invented here. Each is a documented instrument with a
century, or at least a decade, of interpretation and criticism attached —
which is the point of using it rather than a bespoke score.

| In the report | Instrument | Source |
|---|---|---|
| Contribution Distribution | Lorenz curve, Gini coefficient | Lorenz (1905); Gini (1912) |
| Where Change Concentrates | Relative code churn; hotspot analysis | Nagappan & Ball, ICSE 2005; Tornhill, 2013 |
| Change Size per Commit | Relative code churn | Nagappan & Ball, ICSE 2005 |
| Repository Profile | Graphical perception, on reading length rather than area; and why separate petals rather than a radar polygon (ADR 0016) | Cleveland & McGill, JASA 1984; Albo et al., IEEE TVCG 2016; Fuchs et al., IEEE TVCG 2014 |
| What the History Shows | Data-to-text generation | Reiter & Dale, 2000 |
| Chart colours | Color Universal Design; dichromat simulation; contrast | Okabe & Ito, 2008; Viénot, Brettel & Mollon, 1999; WCAG 2.1 |
| The refusal to rank people | Position on individual metrics | SPACE (Forsgren et al., 2021) |

`docs/ARCHITECTURE.md` carries the same table with the reasoning for each
choice, and names what is local to this project — which is where scrutiny
belongs.

## Conventions this project holds to

These are the working rules, not aspirations. They are stated once here
and enforced elsewhere:

- **A guard that has not been observed to fail is not a guard.** Break
  the thing a new test protects, watch it fail, restore it.
- **An empty result from a tool that did not run is not evidence.**
  Check exit codes.
- **Execute the documentation; do not read it.**
- **One branch, one purpose.**

Full contributor detail is in [CONTRIBUTING.md](../CONTRIBUTING.md); the
design record is [ARCHITECTURE.md](ARCHITECTURE.md) and
[adr/](adr/).
