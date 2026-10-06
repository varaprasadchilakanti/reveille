# 0014 — Co-authors are read from trailers and reported as a separate fact

**Status:** Proposed

## Context

Git records one author per commit. A commit made together is credited to its other authors with a
`Co-authored-by: Name <address>` trailer in the commit message — GitHub's documented convention,
which GitHub counts as a contribution for each named co-author. Pair programming, suggestions
accepted in review, and automated fixes all use it: in this repository, two commits by the
maintainer carry `Co-authored-by: Copilot Autofix powered by AI
<…github-advanced-security[bot]@users.noreply.github.com>`.

Reveille reads authors only, so that work is invisible, and a single-maintainer repository that
accepted automated fixes reads as if nobody else had touched it. The author asked for the security
bot to appear.

Two ways were weighed:

- **As authors.** Add each co-author to the charts as a series. Rejected: a co-authored commit
  would then count once per identity, so the share chart and the timelines would stop adding up to
  the number of commits, and every concentration figure would change meaning.
- **As a separate, stated fact.** Chosen. The charts keep counting authors; co-authorship is
  stated beside them.

Reading trailers is new: Reveille has never read commit messages, and the threat model treats
everything in history as written by somebody else. A trailer value can carry any character,
including the record and field separators the main log read splits on (ADR 0004).

## Decision

- **Trailers are read in their own `git log` pass**, one process for the whole history, with the
  same commit selection as the main read (merges excluded, the same date bounds, the same
  `dated_until` cut), emitting only each commit's hash and its `Co-authored-by` values. Git matches
  the key case-insensitively, reads trailers from the last paragraph of a message only, and is
  asked to unfold continuation lines. Nothing else in a message is read.
- **Records are separated by NUL, which a commit message cannot carry, and must line up one for
  one, in order, with the commits `git rev-list` reports.** Matching by hash alone is not enough:
  a review of this record showed that a trailer holding a record separator and a real commit's
  hash forges a record for that other commit, and every hash is public. If the sequence does not
  line up, all co-author data for the run is dropped with a warning; nothing is guessed.
- **At most 32 distinct co-authors per commit** are kept; the rest are dropped and logged.
- **Each value is resolved exactly like an author**: `Name <address>` or it is ignored; the same
  scrubbing, length bounds, `.mailmap` and noreply folding; the address lower-cased as the identity
  key (ADR 0002). A co-author who resolves to the commit's own author is ignored. One matching
  `--exclude-author` is ignored, and the exclusion counts as matched. An excluded author's commits
  credit nobody, since they are not counted at all.
- **The authorship figures do not change.** Commit counts, the share chart, the timelines, the
  Gini, concentration and the ranking count authors only, exactly as before.
  `co_authored_commits` never feeds the ranking and is never a sort key. Identities credited only
  as co-authors are outside `population_size` and the Gini, and the header's "N of M listed"
  counts authors.
- **What is reported:**
  - per listed contributor, `co_authored_commits`: commits they are credited on as a co-author;
  - identities that co-authored but authored nothing in the window, listed apart, alphabetically,
    with the same count, under the `--min-commits` rule of ADR 0011 applied to that count; the
    HTML shows ten and counts the rest;
  - one finding, only when the count is above zero: how many commits credit a co-author, counts
    only, naming nobody.
- **These names appear in the default report**, unlike ADR 0013's area view. ADR 0013 made opt-in
  a new way of organising people; this adds no new lens, only contributors the history itself
  credits, by name and address, in commits anyone can read — the default report already names
  every author. Hiding them would hide the very work this exists to show. The text says "credited
  as co-author" and the caveat says a trailer is not verified.
- **JSON and CSV carry the same facts**: `co_authored_commits` per contributor, `co_authors_only`
  at the top level, `derived.commits_with_co_authors`. `schema_version` stays `1.1`, unshipped and
  additive (ADR 0008) —
  true only while 0.9.0 is untagged; if it ships first, this is a `1.2` change.

## Consequences

**Co-authored work is visible and nothing is double counted.** A co-author is credited where the
history credits them, and every authorship figure still adds up to the number of commits.

**A trailer is a claim made by whoever wrote the message.** It is not verified, as an author field
is not; the section says "credited as co-author", not "co-wrote".

**One more process per run.** Measured on llama.cpp (9,015 commits, 1,562 of them with
co-authors): 0.08 seconds, against about 9 seconds for the whole report. ADR 0004's concern was
one process per commit, which this does not reintroduce.

**Other trailers are not read** (`Reviewed-by`, `Signed-off-by`, `Helped-by`). Each would be a
separate decision about what the report claims.
