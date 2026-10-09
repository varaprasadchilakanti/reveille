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
| [0008](0008-output-provenance-and-schema-version.md) | Output records its own provenance and declares a schema version | Accepted |
| [0009](0009-contributor-licence-agreement.md) | Contributions are accepted under a Contributor Licence Agreement | Accepted |
| [0010](0010-ranking-is-opt-in.md) | The contributor ranking is opt-in, and distribution is measured instead | Accepted |
| [0011](0011-filters-choose-the-listing-not-the-analysis.md) | A filter chooses who is listed, not what the figures are about | Accepted |
| [0012](0012-the-repository-profile-is-a-table.md) | The repository profile is three measures in a table, not five on a radar | Accepted |
| [0013](0013-who-changes-what-is-opt-in-and-area-first.md) | "Who changes what" is opt-in, and organised by area, not by person | Proposed |
| [0014](0014-co-authors-are-a-separate-fact.md) | Co-authors are read from trailers and reported as a separate fact | Proposed |
| [0015](0015-an-interface-for-agents.md) | An interface for agents: summary, who-changed, stdout and bounded lists | Proposed |
| [0016](0016-the-profile-shape-returns-as-a-flower.md) | The profile's shape returns, as six separate petals above the table | Proposed |
| [0017](0017-distribution-figures-count-people.md) | The distribution figures count people; automated accounts are stated beside them | Proposed |
