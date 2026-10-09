# 0017 — The distribution figures count people; automated accounts are stated beside them

**Status:** Accepted (2026-10-09). Partly supersedes ADR 0011's definition of `population_size`, and
changes the population of ADR 0010's Lorenz curve

## Context

The report answers "is this one person's repository or a team's?" in four places: the
Contributors card, "Hold Half the Commits", the Gini coefficient with its Lorenz curve, and the
profile's Shared petal. ADR 0016 made Shared leave automated accounts out, because a dependency
bot is not the "one person" the question is about. The other three still counted them as people.

On this repository at `dc28847` that made the report disagree with itself. One maintainer and
`dependabot[bot]` (86 of 395 commits) read as "2 contributors", a Gini of 0.28 and "Commits are
distributed across 2 contributors", while the profile beside them said Shared 0% and Automation
22%. A reader comparing the two could not tell which was true; both were, of different
populations, and nothing said so.

The research is consistent on what to do:

- Dey et al., "Detecting and Characterizing Bots that Commit Code", MSR 2020: "the automated nature
  of bots can significantly affect the estimates of team size", and bots "should be excluded from
  studies that focus on modeling the behavior of human developers".
- Golzadeh, Decan and Chidambaram, "On the Accuracy of Bot Detection Techniques", BotSE 2022: bots
  "are commonly among the most active project contributors in terms of commit activity. As such,
  tools that analyse contributor activity ... need to take into account the bots and exclude their
  activity." Across 27 projects about 16% of commits were by bots, and in 18 a bot was in the top
  three.

The same paper measures the detection rule. A "bot" suffix on the author name had precision
1.000 and recall 0.520 over 540 accounts: it never called a person a bot, and it missed about half
the bots. Reveille's rule (`[bot]` at the end of the name, or `[bot]@` in the address, the form
GitHub's apps commit under) is narrower still, and has not been measured.

## Decision

- **The distribution figures count people.** Contributors, Hold Half the Commits, the Gini, its
  ceiling and the Lorenz curve, and the distribution finding are computed over contributors that
  the rule does not mark as automated, after `--exclude-author` and regardless of
  `--min-commits`. ADR 0011's rule stands — a filter chooses the listing, not the population — but
  its definition of `population_size` as "the contributors the figures describe" does not: the
  field keeps its name and now counts every contributor, while the figures describe `people`.
  The Lorenz curve that ADR 0010 put in the ranking's place now plots people too.
- **Automated accounts are stated where the figures are.** When any are present, a line under the
  summary cards says how many automated accounts were left out of those figures and how many
  commits they made, and that the rule can miss an account without the suffix.
- **Everything else still counts every commit.** Total commits, lines, the heatmap, the timelines,
  the file charts and the profile's Automation petal describe all the work in the window; the
  contributor table still lists automated accounts, as the facts they are.
- **The JSON says which population each figure describes.** `derived.population_size` stays the
  number of contributors of any kind; `derived.people`, `derived.automated_accounts` and
  `derived.automated_commits` are added. In `reveille summary`, `totals.authors` counts people and
  `totals.automated_accounts` is added. Both are within schema 1.1, which no release has yet
  carried.

## Consequences

- A repository with one maintainer and a dependency bot now reads as one person, which is what it
  is. Its Gini is 0 by definition, as for any single contributor before this decision, and the
  caption says there is no distribution to measure.
- A bot that does not use the suffix is still counted as a person. The report says so in the same
  line; the remedy is `--exclude-author` or a `.mailmap`, both of which already exist.
- A repository made only by automated accounts has no people. The figures read zero and the line
  under the cards states the automated commits; nothing pretends there is a distribution.
- The ranking, which is opt-in and per person, is unchanged: it ranks the rows the table lists.
