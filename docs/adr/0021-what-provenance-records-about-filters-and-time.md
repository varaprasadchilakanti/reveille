# 0021 — What provenance records about filters and time

**Status:** Proposed. Partly supersedes ADR 0008.

## Context

ADR 0008 records that `provenance` carries the `exclude_authors` patterns as requested, names
that as a privacy surface to be handled, and says `--deterministic` pins `generated_at` to the
analysed HEAD commit. It also says the HTML gap — the report itself carries no provenance — is
"tracked for the next release". The 2026-10-09 ADR review found all three no longer describe the
program:

- Since `1b272dc` (2026-09-02) the JSON records `exclude_authors_count`, not the values: writing
  down the names of people who asked to be excluded, in a file meant to be forwarded, defeated the
  exclusion.
- Under `--deterministic`, `generated_at` is the timestamp of the latest commit that survived the
  filters, not of HEAD: HEAD may be a merge, which is never analysed (ADR 0001), and an excluded
  author's later commit is not analysed either.
- Neither 0.8.1 nor 0.9.0 added provenance to the HTML or the CSV.

## Decision

- **Exclusions are recorded as a count only.** The values are never written to any output.
- **Under `--deterministic`, `generated_at` is the latest analysed commit's time.** Without the
  flag it is the clock.
- **The JSON is where provenance lives.** The HTML states the analysed branch, the window, a
  shallow clone, commits dated after the window or not read, replace refs or a graft file not
  followed, and the analysed commit for a
  detached HEAD; the CSV is the contributor table alone. Adding a full provenance block to the
  HTML is not decided here.

## Consequences

- A filtered report cannot be re-run from its provenance alone: the person re-running it needs
  the exclusion values from whoever made it. That is the price of not publishing them.
- Two deterministic reports of the same commit with different exclusions can carry different
  `generated_at` values, correctly: they describe different sets of commits.
