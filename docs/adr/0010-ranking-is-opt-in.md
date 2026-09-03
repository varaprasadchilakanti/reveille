# 0010 — The contributor ranking is opt-in, and distribution is measured instead

**Status:** Accepted

## Context

Reveille has always assigned each contributor a composite score, a percentile,
and a military tier designation from Private to Commander, weighted 30% commits,
25% lines changed, 25% consistency, 20% recency. It was on by default.

Every release since has added a caveat around it rather than changing it. v0.7.0
documented that the weights are a judgement and not a derived model, stated in
the README, the User Guide and the module docstring that the ranking measures
volume and regularity of commits rather than contribution, productivity or
value, and cited DORA and SPACE, both of which say explicitly that their measures
must not be used to assess individuals. v0.8.0 went further and put that refusal
into machine-readable form, so an agent reading `reveille capabilities` is told
the tool is not fit for performance review, compensation, promotion, redundancy
or hiring.

All of that was true and none of it changed what a person saw when they ran the
command. The default report still opened with named individuals ranked by score
and labelled with a rank.

Two things made the position untenable rather than merely awkward.

**The project's own stated non-goal contradicted its default behaviour.** The
strategy record lists individual developer performance measurement first among
the things Reveille is not for. A default that ranks humans by lines of code is
that measurement, whatever the surrounding prose says.

**Documentation does not travel with the artefact.** The HTML report is designed
to be forwarded — attached to a review, pasted into a channel, handed to a
manager. The caveats stay in the repository. The foreseeable failure is somebody
opening a report they did not generate, seeing "Commander" beside a colleague's
name, and drawing exactly the conclusion the documentation asked them not to.

A separate finding sharpened it. v0.8.0's provenance work records the exact
ranking weights into every report, which is honest, and which also means a
default report now permanently carries the formula used to rank named people.
That raises the stakes rather than lowering them.

## Decision

**The ranking is off by default from 0.8.0.** `--ranking` turns it on;
`[ranking] enabled = true` does the same in `reveille.toml`. `--no-ranking`
remains and still works, so no existing invocation breaks.

When it is off, the ranking fields are **absent** from the JSON rather than
present with sentinel values. A key reading `"tier": 0` is a number a consumer
can mistake for data; an absent key cannot be misread, and
`provenance.ranking.enabled` says which shape to expect.

**In its place, the default report measures the distribution rather than the
people.** A Lorenz curve plots the cumulative share of commits against the
cumulative share of contributors, against a diagonal of perfect equality, with
the Gini coefficient as the single-number summary of the gap.

Both are borrowed, and that is the reason for choosing them. The Lorenz curve
(1905) and the Gini coefficient (1912) are the standard instruments for
concentration in a population, with a century of interpretation and known
weaknesses behind them. What they replace — "how many contributors account for a
majority of commits" — had no literature behind it, no defined range, and a step
change in value whenever one contributor crossed half.

Critically, **neither names anybody.** The curve is unchanged by who sits where
in it. It answers a question about the repository, which is what the tool is for.

## Consequences

**This is a breaking change to default output** in every format. A caller who
relied on `tier` or `composite_score` appearing must now pass `--ranking`. That
is the intended cost: the previous default was the problem.

**Some users will find the tool less immediately impressive.** A ranked table
with rank designations is more arresting than a distribution curve. That is
precisely why it was the wrong default.

**The Gini coefficient can be misread too**, and the report says so where it is
shown. It describes shape, not health. A single-maintainer project scores 0 by
definition; a project with one maintainer and many occasional contributors scores
high for entirely ordinary reasons. Its maximum for a sample of *n* is
`(n-1)/n`, so it must not be compared across repositories with very different
contributor counts. Substituting a well-known metric for an ad-hoc one improves
the ceiling on how carefully it can be read; it does not remove the need to read
it carefully.

**The ranking is not deleted, and should not be.** It is a legitimate thing to
look at deliberately, for your own repository, having read what it does and does
not mean. The change is to who decides: it now takes an explicit act, and the
person performing it has passed the documentation on the way.
