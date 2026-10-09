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
| [0002](0002-email-as-identity-key.md) | Email is the contributor identity key | Accepted; extended by 0020 |
| [0003](0003-bisect-left-for-percentile-ties.md) | Percentiles use lower-bound ranking | Accepted |
| [0004](0004-single-pass-numstat-read.md) | History is read in a single `git log --numstat` pass | Superseded by 0019 |
| [0005](0005-commit-concentration-not-bus-factor.md) | The concentration metric is not called a bus factor | Accepted |
| [0006](0006-offline-single-file-report.md) | The report is a single offline file | Accepted |
| [0007](0007-apache-2-0-licence.md) | The licence moves from MIT to Apache-2.0 | Accepted |
| [0008](0008-output-provenance-and-schema-version.md) | Output records its own provenance and declares a schema version | Accepted; partly superseded by 0021 |
| [0009](0009-contributor-licence-agreement.md) | Contributions are accepted under a Contributor Licence Agreement | Accepted |
| [0010](0010-ranking-is-opt-in.md) | The contributor ranking is opt-in, and distribution is measured instead | Accepted |
| [0011](0011-filters-choose-the-listing-not-the-analysis.md) | A filter chooses who is listed, not what the figures are about | Accepted; partly superseded by 0017 |
| [0012](0012-the-repository-profile-is-a-table.md) | The repository profile is three measures in a table, not five on a radar | Accepted; partly superseded by 0016 |
| [0013](0013-who-changes-what-is-opt-in-and-area-first.md) | "Who changes what" is opt-in, and organised by area, not by person | Accepted |
| [0014](0014-co-authors-are-a-separate-fact.md) | Co-authors are read from trailers and reported as a separate fact | Accepted |
| [0015](0015-an-interface-for-agents.md) | An interface for agents: summary, who-changed, stdout and bounded lists | Accepted |
| [0016](0016-the-profile-shape-returns-as-a-flower.md) | The profile's shape returns, as six separate petals beside the table (above it on a narrow screen) | Accepted |
| [0017](0017-distribution-figures-count-people.md) | The distribution figures count people; automated accounts are stated beside them | Accepted |
| [0018](0018-replace-refs-are-not-honoured.md) | Reveille reads the objects its hashes name; replace refs are not honoured | Accepted |
| [0019](0019-how-history-is-read.md) | How history is read: three reads, an allowlist, and nothing lost without a word | Proposed |
| [0020](0020-exclude-author-removes-a-person-by-address.md) | `--exclude-author` removes a person by every address the value reaches | Proposed |
| [0021](0021-what-provenance-records-about-filters-and-time.md) | What provenance records about filters and time | Proposed |

## Notes from the review of 2026-10-09

An accepted record is not edited (CLAUDE.md). Where one has drifted from the program without its
decision changing, the drift is noted here instead; where its decision changed, a later record
supersedes it, and the table says so. The review itself is kept outside the repository.

- **0001.** The `no_merges=True` wording is old; the decision holds and is tested. Not stated in
  the record: a change made only in a merge commit, such as a conflict resolution, is not counted,
  and a person whose only commits are merges does not appear.
- **0002.** In a bare repository Reveille reads no `.mailmap`, while Git applies `HEAD:.mailmap`;
  a known issue in 0.9.0.
- **0003.** The decision holds. The defect its context describes did not occur: `.index` on a
  sorted list already returned the first equal element.
- **0005.** The report labels the figure "Hold Half the Commits".
- **0006.** The bundled Plotly (7.1.0) is about 4.8 MB, not 3.5, and holds 55 `https://` strings,
  not 16, some of them map-tile endpoints. What keeps them unused is the trace-type allowlist
  (bar, pie, scatter), which the tests enforce. Offline at run time is recorded in 0019.
- **0007.** The Poetry version named is the one at the time.
- **0010.** Its DORA sentence is not supported by the DORA guide and was removed from the
  published documents in 0.9.0. A `rank` field, in table order, remains in JSON and CSV with
  ranking off; a known issue.
- Undated measurements in 0004, 0005 and 0006 were measured when each record was written.
