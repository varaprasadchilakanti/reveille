# 0011 — A filter chooses who is listed, not what the figures are about

**Status:** Accepted

## Context

Reveille has two filters that read as interchangeable. `--exclude-author` drops a
contributor by name or email. `--min-commits` drops every contributor below a commit
threshold. Both remove rows from the contributor table.

They did not behave the same way, and neither behaviour was stated anywhere.

Measured on this repository, split 238 commits to 84 between two contributors:

| | `total_commits` | rows sum to | residual | `gini_coefficient` |
|---|---|---|---|---|
| no filter | 322 | 322 | 0 | 0.24 |
| `--min-commits 100` | 322 | 238 | **84** | **0.00** |
| `--exclude-author` | 238 | 238 | 0 | 0.00 |

Three defects, of different kinds.

**The Gini was computed over the survivors.** `--min-commits 100` removed the
contributor who made the split uneven, and the coefficient was then taken over the
remaining population of one. The report stated `0.00` — perfect equality — for a
repository that is 74/26. That is not a rounding artefact or a presentational
choice; it is the wrong answer to a question about the repository.

**The difference was undeclared.** `total_commits` stayed at 322 while the single
listed row read 238. The HTML said nothing: no occurrence of `min_commits`,
`minimum`, `threshold` or `filter` anywhere in its authored content. A reader who
noticed the discrepancy could recover the suppressed contributor's exact commit
count by subtraction — the pattern statistical disclosure control calls
complementary suppression — and a reader who did not notice simply had two numbers
that disagreed.

**The two filters disagreed with each other.** `--exclude-author` recomputed the
denominator; `--min-commits` did not. Whichever is right, they cannot both be.

## Decision

**A filter chooses who is listed. Every figure describes the whole repository, and
the difference is stated in the artefact.**

Concretely:

- Contributors held back by `min_commits` are still aggregated. They are carried on
  `ReportData.suppressed_contributors` and included in the population used for the
  Gini coefficient, the Gini ceiling, commit concentration and the written findings.
- `total_commits` continues to count every commit in the window. It was already
  right; what was missing was the explanation.
- `metadata.unique_contributors` continues to mean *contributors listed*. Its meaning
  does not change, so no consumer breaks.
- Two fields are added under `derived`: `population_size`, the number of contributors
  the figures describe, and `contributors_below_threshold`, how many were held back.
  A consumer can now reconcile the rows against the total without arithmetic.
- The HTML states it in the header, beside the branch and the period: how many of how
  many contributors are listed, the threshold that held the rest back, and that their
  commits are still counted in every figure.
- `schema_version` moves from `1.0` to `1.1`. Purely additive, per ADR 0008, which
  also supplies the reason: an output change a consumer has no way to detect is
  precisely what the version exists to prevent.

## Consequences

**A report using `--min-commits` no longer claims a distribution it did not measure.**
The coefficient is the same number with the filter on and off, which is what makes it
a statement about the repository rather than about the flag.

**The residual is still computable, and that is deliberate.** Recomputing the total to
hide the gap was the alternative, and it would have made `--min-commits` behave like
`--exclude-author`. It was rejected because it removes information the reader is
entitled to — that the repository has contributors this report is not showing — in
order to obscure an inference that anyone with `git shortlog -sne` can make anyway.
Suppression that only works against a reader without the repository is not protection;
it is a smaller report that looks like protection. A reader who should not know the
figures should not be given the report.

**`--exclude-author` keeps its existing behaviour and is now the documented difference.**
It answers a different question — "show me this repository without this person's
commits" — and removing them from the total is correct for that question. The two
filters are no longer interchangeable by accident; they are distinct by decision.

**One degenerate case was fixed alongside this.** With one contributor the Gini ceiling
is `(1-1)/1 = 0`, and the caption rendered as *"Gini runs 0 (even) to 0.00, which is the
most concentrated 1 contributors can be"* — a vacuous range and a grammatical error in
shipped output. It now says that a single contributor has no distribution to measure.

**This does not make small-*n* reports anonymous, and must not be described as though it
does.** With two contributors, the coefficient plus one person's knowledge of their own
count still determines the other's exactly. The report names every listed contributor
and prints their email address. Nothing here changes that, and no document may cite the
Lorenz curve or the Gini coefficient as a de-identification measure.
