# Architecture Decision Records

Each record captures one decision that shaped Reveille, the situation
that forced it, and what it cost. They exist so a decision is not
silently reversed by someone who never saw the reasoning — and so a
decision that *should* be reversed can be, with its original argument in
view rather than reconstructed from memory.

A record is written when a decision is hard to infer from the code.
Routine choices do not need one.

Records are immutable once accepted. A decision that changes gets a new
record that supersedes the old one; the old record stays, marked
superseded. The history is the point.

## Format

**Context** — the situation and the constraint. **Decision** — what was
chosen, stated plainly. **Consequences** — what this costs, including
what it rules out. **Status** — Accepted, Superseded by NNNN, or
Deprecated.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-exclude-merge-commits.md) | Merge commits are excluded unconditionally | Accepted |
| [0002](0002-email-as-identity-key.md) | Email is the contributor identity key | Accepted |
| [0003](0003-bisect-left-for-percentile-ties.md) | Percentiles use lower-bound ranking | Accepted |
| [0004](0004-single-pass-numstat-read.md) | History is read in a single `git log --numstat` pass | Accepted |
| [0005](0005-commit-concentration-not-bus-factor.md) | The concentration metric is not called a bus factor | Accepted |
| [0006](0006-offline-single-file-report.md) | The report is a single offline file | Accepted |
| [0007](0007-apache-2-0-licence.md) | The licence moves from MIT to Apache-2.0 | Accepted |
