# 0003 — Percentiles use lower-bound ranking

**Status:** Accepted

## Context

Contributors are converted from composite scores to percentiles, and
percentiles decide tiers. Ties are common: in a small repository several
people genuinely have identical scores, and after min-max normalisation
exact equality is easy to hit.

The original implementation used `list.index` on the sorted scores.
`list.index` returns the position of the first equal element as
encountered, which meant tied contributors could receive different
percentiles depending on list order — and therefore different tiers, for
identical work. The result was not reproducible between runs.

## Decision

Percentiles use `bisect.bisect_left` over the sorted scores, giving
lower-bound rank semantics:

```
percentile = bisect_left(sorted_scores, score) / (n - 1) * 100
```

Tied scores receive the same rank, so they receive the same percentile
and the same tier. A single contributor is defined as 100.0.

## Consequences

Ties are handled predictably and identically on every run, which is the
whole point.

Lower-bound means a tied group is placed at the *bottom* of its band —
three contributors tied at rank 5 all get rank 5, not 6 or 7. This is
the conservative reading and the conventional one, but it does mean the
percentile of a tied group is lower than an average-rank method would
give.

`bisect_left` is also O(log n) rather than `list.index`'s O(n). That is
not why the change was made, and it does not matter at these sizes.
