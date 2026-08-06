# 0005 — The concentration metric is not called a bus factor

**Status:** Accepted

## Context

The report showed a summary card labelled "bus factor", computed as the
number of contributors accounting for a majority of commits.

That is not a bus factor. A bus factor asks how many people would have
to leave before the project loses the ability to maintain some part of
itself — a question about **knowledge ownership**, which is a property
of who understands which code, approximated by who has written and
maintained it.

Commit count answers a different question: who has been *active*. The
two diverge in ordinary cases. Someone who wrote a critical subsystem
years ago and has committed rarely since is a large bus-factor risk and
a small commit-count presence. Someone doing high-volume mechanical
changes is the reverse.

The label was the problem, not the number. "Bus factor" is a term of art
with an established meaning, and using it for a different quantity meant
the report was making a claim about risk that its own data could not
support — in a document written to be forwarded to stakeholders.

## Decision

The metric is named **commit concentration** in the UI, the code
(`_compute_commit_concentration`), and the JSON payload
(`derived.commit_concentration`). The User Guide states explicitly that
it is *not* a bus factor.

Computing a real bus factor was considered and rejected for now: it
needs per-file ownership via `git blame`, measured at ~12.5 ms per file
— minutes on a large repository, against the ~40 seconds the whole
analysis currently takes. See
[0004](0004-single-pass-numstat-read.md).

## Consequences

The report no longer implies a risk assessment it cannot make. What it
shows is honest and still useful: concentration of activity is real
information.

The JSON key changed, which is **breaking** for anyone reading
`derived.bus_factor`. It was accepted pre-1.0 rather than carrying a
misleading name into the stable API.

A real bus factor remains a legitimate future feature. It would be a new
metric alongside this one, with its own cost documented — not a
rename back.
