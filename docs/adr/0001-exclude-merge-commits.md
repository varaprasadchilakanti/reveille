# 0001 — Merge commits are excluded unconditionally

**Status:** Accepted

## Context

A merge commit records that two lines of history were joined. In a
squash-and-merge or pull-request workflow it carries no authored change
of its own, and its diff against the first parent can be enormous —
every line from the merged branch, attributed to whoever pressed the
button.

Counting them inflates commit totals and line volumes for whoever
performs merges, typically maintainers and release managers, in a way
that has nothing to do with what they wrote.

## Decision

`GitReader.read_commits` passes `no_merges=True` unconditionally. There
is no flag to include them.

## Consequences

Reveille's figures are lower than `git log --oneline | wc -l` on a
repository that merges frequently. This surprises people who compare the
two, so the User Guide states it.

Merge-heavy workflows are not measurable through Reveille: a team whose
integration work genuinely lives in merge commits will see that work
missing. This is accepted rather than solved, because the alternative —
counting merges — misattributes far more often than it informs.

Making it configurable was considered and rejected. It would put a
switch on the meaning of every number in the report, so two reports
could not be compared without checking how each was generated.
