# Playbook

How to read a Reveille report and act on it, for whoever holds it: a manager, a maintainer or an
agent summarising it for someone else. This page states *use*; what the measures are is in
[USER_GUIDE.md](USER_GUIDE.md), and the machine-readable version is
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

This is the report's own order: findings first, evidence after. Stop at the first section that
answers your question. What each section contains is in
[USER_GUIDE.md](USER_GUIDE.md#understanding-the-report).

## What each measure supports, and what it does not

| Measure | Supports | Does **not** support |
|---|---|---|
| Commit count | How much recorded activity there was | How much work was done |
| Contributors, Gini | How activity is spread across people; automated accounts with `[bot]` are stated apart | How many people work on the code: review, pairing and unmerged work leave no commit |
| Gini / Lorenz | Whether activity is concentrated | Whether that is a problem |
| Commit concentration (the "Hold Half the Commits" card) | How few people hold most commits | A bus factor; it says nothing about who *knows* the code |
| Active days | Regularity of committing | Hours worked |
| Lines added/deleted | Size of recorded change | Quality, difficulty, or value |
| Weekend finding (stated when more than 15% of commits fall on a weekend) | When commits were timestamped | Overwork — time zones and rebases move commits across the boundary |
| Ranking (`--ranking`) | Volume and regularity, nothing else | Any assessment of a person |

The ranking is off by default and should usually stay off. JSON and CSV still carry a `rank` column,
in table order (by commits; by score with `--ranking`). The SPACE framework (Forsgren et al.,
2021) holds that "developer productivity is about more than an individual's activity levels";
[ADR 0010](adr/0010-ranking-is-opt-in.md) records why this project does not rank people by default.

## Three questions it answers well

**"Has anything been committed lately?"**
`reveille generate --repo . --since 2025-01-01`. Read the timeline and the dormancy finding. A flat
tail means no commits in the window; it does not say why. Released software commits rarely.

**"Is most of the activity from one or two people?"**
Read the distribution finding and the Lorenz curve. A high Gini with a
short contributor list describes commits. It is not a bus
factor: someone may know the code without having committed recently.

**"What changed between two periods?"**
Run twice with different `--since`/`--until` and compare. Use
`--deterministic` so only the history differs between runs, and `--format
json` so a diff is readable.

## Three it answers badly

- **Comparing two repositories.** A Gini of 0.6 means different things
  in a library and a monorepo. These figures are comparable against the
  same repository over time.
- **Anything about an individual.** See the table above.
- **Anything about code quality.** Reveille receives commit history,
  paths and line counts, not file contents (Git reads the files to
  compute the counts). It cannot see a test, a review, or a defect.

## For an audit or due diligence

1. **Make the run repeatable.** `--deterministic` takes the end of the window
   and the generation time from the last commit, so the same repository gives
   the same bytes on the same Reveille version, installed dependencies and
   Git settings.
   Keep the JSON: `provenance` records the Reveille version,
   the analysed commit hash, whether a `.mailmap` was applied, whether the
   clone was shallow, and the filters as requested.
2. **Reconcile before relying.** `metadata.total_commits` should match
   `git rev-list --no-merges --count <commit>` over the same window; merge
   commits are excluded by design.
3. **Know what it is not evidence of.** Author names and addresses are
   whatever the committer's Git was set to; Reveille does not verify them,
   and it does not read who reviewed, approved or merged a change. Commit
   history shows that changes were made, not that they were authorised.

## For agents and scripts

Read [llms.txt](../llms.txt) first; it is the short index. `reveille skill` prints the commands
to put in an agent's instructions: `state` at the start of a task, `brief` for what changed,
`who-changed` before changing a file. `repos <dir>` gives one row per repository in a directory.
Then:

1. **Ask, do not guess:** `reveille capabilities --format json` reports
   the command surface, its `guarantees` field (properties designed and
   tested; not a warranty) and the exit codes, read from the running
   program.
2. **Branch on the exit code, not on stdout.** `0` affirmative, `1` ran
   correctly with a negative answer, `2` could not run.
3. **Check `schema_version` before parsing**, and carry `provenance`
   into whatever you produce; two reports that disagree are reconciled
   from it.
4. **Pass `--deterministic`** for anything cached, diffed, or compared.
5. **Never present a ranking as an assessment**, and never name an
   individual in a summary the default report does not name. The
   generated findings follow this; anything built on top should too.
6. **Count small numbers as identifying.** `summary` and `brief` name
   nobody, but with one or two people their counts can identify someone.
   `state` names no author but lists local paths and the branch name.

## Where the measures come from

The published instrument behind each measure is listed in
[ARCHITECTURE.md](ARCHITECTURE.md#lineage). Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md).
