# 0019 — How history is read: an allowlisted log, and nothing lost without a word

**Status:** Accepted (2026-10-09). Supersedes ADR 0004.

## Context

ADR 0004 recorded that history is read "in a single `git log --numstat` pass" and that the field
separators it splits on cannot occur in a name, so "no author can break the parse". Neither is
true of the reader on 2026-10-09, and the second was never true:

- The reader runs three Git reads per analysis: `git rev-list` for the commit set, `git log`
  (with `--numstat` unless line counts are not needed) for the records, and a second `git log -z`
  for `Co-authored-by` trailers (ADR 0014).
- A commit can be written with any bytes in its author field (`git hash-object --literally`).
  One carrying the record separator `\x1e` splits its record in two. The defence, added before
  this record, is that a record counts only if it has four fields and an object name that
  `rev-list` computed; the fragments fail that check and are dropped. Measured in the 2026-10-09
  ADR review: such a commit was dropped **silently** — Git counted 2 commits, the report 1.
- Settings in a user's or a repository's Git configuration can change what a read returns
  (`log.follow`, replace refs, a graft file), and a partial clone makes Git fetch missing objects
  from the network and write them into `.git/objects` (found and fixed 2026-10-09).

What ADR 0004 decided — one log read for the whole history, never one process per commit — still
holds and is kept. What it said about safety and about how many reads there are is replaced here.

## Decision

- **One `git log` read for the records, one `git rev-list` for the commit set, one `git log -z`
  for trailers**, and, only when an author is excluded, one more `git log` reading names and
  addresses across all history (ADR 0020). Never one process per commit.
- **`rev-list` is the allowlist.** A record counts only if it has the expected shape and an object
  name `rev-list` reported. The trailer read must line up with `rev-list` one for one (ADR 0014).
- **A commit that cannot be read is counted and stated, never lost silently.** The number of
  `rev-list` commits with no well-formed record is warned on stderr, shown as a "Not read" line in
  the report's header, and recorded as `provenance.commits_unreadable`.
- **Settings that change what is read, or what a read runs, are fixed for every read**:
  `log.follow=false`; `log.showSignature=false`, which a repository's own configuration could set
  to make every log run its `gpg.program`; `GIT_NO_REPLACE_OBJECTS=1` and an empty graft file
  (ADR 0018); `GIT_NO_LAZY_FETCH=1`; `--end-of-options` before the revision; date boundaries in
  UTC; `--since-as-filter` where Git supports it.
- **A partial clone is refused before any read**, judged from its configuration (a promisor remote
  or `extensions.partialClone`), with exit 2.

## Consequences

- A forged author field can still make a commit unreadable, but no longer invisible: the report
  says how many, and the totals are honestly smaller.
- A clone made with `--filter` is refused even when the server did not honour the filter and
  nothing is missing; the remedy is a clone without `--filter`. Refusing on configuration keeps the
  promise on any Git version, where detecting a missing object would require reading it.
- Three processes, not one: measured costs are in ADRs 0004 and 0014; none is per commit.
