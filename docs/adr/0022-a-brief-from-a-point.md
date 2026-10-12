# 0022 — A brief from a point: `reveille brief --from`

**Status:** Accepted (2026-10-12). Proposed the same day.

## Context

The question a developer returning to a repository, or an assistant starting a session, asks
first is *what changed since a point I know?* Reveille cannot answer it today:

- `summary` (ADR 0015) describes the whole window: the Gini, the quiet run and the findings are
  measures of a period, and they change meaning over a short range.
- `--since` takes a date. The point people know is usually a release tag or the commit they last
  saw, and a date is the wrong cut for it: a commit authored before the tag can land after it.
- An assistant falls back to `git log v0.9.0..HEAD` and counts in its own context, which costs
  tokens and leaves the arithmetic, the identity resolution and the merge rule to it.

The word means the call that starts a day, and a brief is what the tool's name promises.
Range comparison exists in forge compare views and older report tools, but no tracker request
for it in comparable tools was found with more than a handful of reactions: this is argued from
use, not measured.

## Decision

**A new command, `reveille brief`, that describes what changed between a point and the analysed
branch, in counts, naming nobody.**

- **The point.** Exactly one of `--from <revision>` (a tag, a branch or a commit) or `--since
  <YYYY-MM-DD>`. A revision means ancestry, as `git log <revision>..<branch>` does: the commits
  reachable from the branch and not from the revision. It is resolved locally with
  `git rev-parse --verify --end-of-options <revision>^{commit}`, under the same environment and
  pins as every read (ADR 0019): no fetch, a value starting with `-` refused, exit 2 if it does not
  resolve. A revision that is not an ancestor of the branch is allowed and stated.
- **What it says**, all aggregate:
  - commits in the range (merges excluded, ADR 0001), people and automated accounts as counts
    (ADR 0017), commits crediting a co-author;
  - the five areas (ADR 0013's depth) and file types with the most commits;
  - how many files appeared for the first time;
  - areas that changed in the range after at least 90 days without a commit;
  - tags whose commit lies in the range;
  - the analysed commit, printed so a caller can pass it as the next `--from`.
- **What it does not say:** names or addresses of anyone, line counts (none are read, so it is as
  fast as `summary`), and any measure of a period (Gini, concentration, quiet run).
- **Output:** text under 1 KB and `--format json` (a `"document": "brief"` beside
  `schema_version`); the notice every answer carries; `--limit` bounds the area, type and tag
  lists. Exit 0 answered, 1 no commits in the range, 2 could not run.
- **No state.** Reveille remembers nothing between runs. "Since my last look" is the caller
  passing back the commit the previous brief printed.

## Alternatives considered

- **`summary --from`.** Rejected: `summary`'s measures describe a period, and over a short range
  they would mislead (a Gini of three commits) or need a second set of rules inside one command.
- **`--since <tag>`, a date or a revision in one option.** Rejected: `--since 2025-01-01` is
  ambiguous when a tag has that name, and the two cut history differently (date versus ancestry).
- **Remember the last run.** Rejected: it needs a file. Inside `.git` is refused (the output rules,
  `SECURITY.md`); in the working tree it is a file the user did not ask for.
- **Name the new contributors.** Rejected for the default: a brief is meant to be passed on. A
  count says that someone new arrived; `who-changed` names people for a path when asked.
- **Line counts per area.** Deferred: they double the cost and the ranking by commits answers
  "where did the work go".

## Consequences

- **A brief between two commits is reproducible without `--deterministic`.** It depends on the two
  commits alone; no clock enters. With `--since` the window ends at the clock, as for `summary`.
- **Small numbers can still identify people.** "1 new person" in a team that knows who joined
  names them. The same caveat as `summary` is stated beside the count.
- **Area paths and tag names are repository text.** They are escaped on output, as `summary` and
  `who-changed` output is and may themselves name people (a
  `users/jsmith/` area, a tag such as `jsmith-test`).
- **Schema 1.2.** A new document type is additive; `schema_version` becomes `1.2` with the
  release that ships it, together with the branch section if that lands the same release.
- **One more command.** It reuses the reader with a revision range, the area and identity rules,
  and the output rules; one new read of names and statuses (`--name-status`, no line counts) for
  "first appearance" and areas.
- **`--from` is the spelling everywhere it is added.** If `generate` and `summary` later take a
  revision point, they take `--from`, decided by this record, not reopened.
- **Not called a briefing service, a monitor or an alert.** It runs when asked and ends.
