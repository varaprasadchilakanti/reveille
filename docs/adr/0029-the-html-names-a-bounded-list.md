# 0029 — The HTML report names at most 1,000 people, or `--limit`

**Status:** Proposed (2026-10-19). Extends `--limit` from
[ADR 0015](0015-an-interface-for-agents.md) to the HTML report; the rest of 0015 stands.

## Context

The HTML report listed every contributor: in the contributor table, in the heatmap's list of
people, and as a bar each in the lines chart. Its Lorenz curve had one point per person. Measured
on 2026-10-19, on a synthetic repository of 100,000 commits by 100,000 authors, the report was
78 MB and took 6.9 s. The table was 52 MB of that, the heatmap payload 8 MB, the lines chart and
its table 8.5 MB, and the Lorenz curve and its table 7.7 MB.

Three things weigh against a list of every name:

- **What readers need.** The 2026-10-17 research found readers asking for a first-hour picture of
  a repository, and rejecting commit counts as a way to manage people. A table of 100,000 names
  answers neither need, and no browser shows it usefully.
- **Privacy.** A report is forwarded, and each name and address in it goes wherever the report
  goes. Naming fewer people than the figures count is data minimisation. Every figure still
  describes everyone.
- **`--limit` already exists** for JSON and CSV, and was documented as not bounding the HTML. A
  person who wanted a shorter list of names in the page had no way to ask for one.

## Decision

**The HTML report names at most the first 1,000 listed contributors, in table order. `--limit`
sets that number instead when it is given. Every figure is still computed over everyone.**

- **What the bound applies to:** the contributor table, the heatmap's list of people and the lines
  chart. The pie and the timeline already show a fixed few.
- **Saying so:** when the bound cuts the list, the page says how many of how many are shown, that
  the figures count everyone, and that JSON and CSV list everyone unless `--limit` is given.
- **The Lorenz curve** is drawn from at most 201 evenly spaced points of the full curve, both ends
  included. Each point drawn is a point of the exact curve, and the Gini is computed from every
  count.
- **JSON and CSV are unchanged:** they list everyone unless `--limit` is given.

## Consequences

- At 100,000 authors the report is 2.5 MB and takes 3.8 s (same machine and repository). Every
  stat card and every finding is unchanged, and so is the Gini. A report with fewer than 1,001
  listed people and 201 curve points is byte-identical to the report before this change (checked
  on this repository with `--deterministic`).
- A reader who needs a complete list of names has to ask for JSON or CSV. That is deliberate.
- `--limit` now changes the HTML. A run that used `--limit` with the HTML format, where it used to
  do nothing, now shows fewer rows.
- The number 1,000 is a judgement, not a measurement: well past any team that reads a table, and
  well short of the size at which the page stops loading.
