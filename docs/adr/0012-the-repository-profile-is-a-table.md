# 0012 — The repository profile is three measures in a table, not five on a radar

**Status:** Accepted

## Context

The repository profile was a five-axis radar: Spread, Continuity, Recent work, Revisiting,
Small steps. Every axis was a naturally bounded share, deliberately never rescaled, and the
module docstring argued carefully against its own chart form — citing Cleveland and McGill
(*Graphical Perception*, JASA 1984) on area being read far less accurately than position or
length, and on the enclosed area depending on an axis order that carries no meaning. It
mitigated by fixing the order, labelling every vertex, and printing in the report:

> Read it as five numbers, not as a shape.

That sentence is the argument for this decision. A figure that must be read as numbers is
better presented as numbers. The caveat was an admission, not a mitigation.

Two research passes, run independently and without contact, reached the same conclusions about
the axes. Both were checked by measurement rather than accepted.

**`Spread` restated a figure printed elsewhere.** It was exactly `1 - Gini / ((n-1)/n)` — a
monotone transform of the Gini coefficient shown in the Contribution Distribution section a few
hundred pixels above, where it carries better caveats. It also returned a hard-coded 0.0 for a
single contributor, described as "one contributor, so there is nothing to spread", which plotted
*undefined* at the same position as *worst possible*. Four measured scenarios meaning four
different things all read 0.00, while "one dominant contributor out of ten" — the case the axis
existed to show — read 0.10.

**`Small steps` restated another.** Its threshold was chosen to match the third bucket boundary
of the change-size histogram, so it was exactly the first three bars of that chart, summed. It
could not tell a different story, only the same one twice. Measured across eleven real windows it
ranged 0.500–0.864, so it was not degenerate — it was redundant.

**A third problem was not about the axes but about the reader.** The radar carried `role="img"`,
which makes an SVG's children presentational, so its `aria-label` was the whole of what a
screen-reader user received — and that label named "currency of the last commit", an axis
`_recent_share` had replaced. The figures themselves lived in a `visually-hidden` table that
sighted readers never saw. With JavaScript off the section drew nothing at all. Three audiences,
three different wrong answers.

**A fourth: the numbers were uninterpretable.** `Continuity` on this repository reads 0.913. That
looks strong. Under commits placed uniformly at random across the same window it would read about
0.99, so 0.913 is *below* what chance alone would give. Nothing in the report let a reader know
that, and a bare bounded share with no reference point cannot be read as high or low at all.

## Decision

**Three measures — Continuity, Recent work, Revisiting — rendered as a table with bars in it.**

- `Spread` and `Small steps` are removed. Each restated a figure the report already prints.
- The section is HTML and CSS: a `<table>` whose cells contain a track and a fill. Not Plotly.
- Each measure shows, beside its value, **the value it would take under evenly spread activity**,
  where that follows from the measure's own arithmetic. Continuity's is `1 - (1 - 1/W)**C` for C
  commits over W weeks. Recent work's is the share of the window's days its final quarter
  occupies — computed rather than assumed to be a quarter, because the cut-off is inclusive.
  Revisiting has none and is shown without one.
- The column is headed **"Expected by chance"** and the section states that it is not a target.

## Consequences

**A computed expectation is not an invented norm, and the distinction is load-bearing.** The
objection to marking a reference value is that it turns a description into a scorecard, and
`profile.py` says plainly that none of these axes is a target. That objection holds against a
number somebody *chose* as good. It does not hold against a number derived from the measure's own
construction: that a repository is above or below what random placement would produce is a fact
about the measure, not an opinion about the repository. Where no such number can be derived, none
is shown — which is why `Revisiting` has an em dash and not a guess.

**The profile no longer reads contributor data at all.** `Spread` was the only axis that did, so
`repository_profile` now takes commits, files and a window. It cannot name, rank or count people
even by accident, and no listing filter can reach it.

**Three audiences now read the same markup.** It renders with JavaScript off, it is visible to
sighted readers, and it needs no `role="img"` and no `aria-label`, because it is text. Verified
by rendering it through an engine that supports almost no CSS: every figure remained present and
legible.

**One Plotly trace type stopped being used.** `scatterpolar` had no other user, so the report now
emits `bar`, `pie` and `scatter` only. The offline guarantee's trace-type allowlist — the one
guard that can catch a map trace, because a map specification contains no URL for any text check
to find — is one entry smaller.

**What is given up.** A radar is recognisable: the same repository produces a similar silhouette
next time. That was the form's one genuine strength, and this decision discards it. It was
measured before being discarded — over windows advancing month by month on this repository the
axes moved non-monotonically and no stable silhouette appeared — but the measurement covered one
repository, and "unevidenced" is not the same as "false". Some readers will prefer the picture.

**This supersedes nothing.** No earlier ADR covered the profile's form. The axis set is now fixed
in two places — `AXIS_ORDER` and a literal in `tests/unit/domain/test_profile.py` — so changing it
again is a deliberate act rather than a silent one.
