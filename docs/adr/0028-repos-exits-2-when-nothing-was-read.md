# 0028 — `repos` exits 2 when no repository it found could be read

**Status:** Accepted (2026-10-23). Proposed 2026-10-19. Supersedes, in 0026, the consequence that a repository's
refusal never changes the exit code; the rest of 0026 stands.

## Context

[ADR 0026](0026-many-repositories-one-row-each.md) made a repository that cannot be read a row
saying why, so that one partial clone does not stop a run over a hundred mirrors. It followed that
the exit code no longer meant "every input was read", and `repos` exited 0 whatever its rows said.

That rule held one case it was not written for: every repository found refused. A directory of
partial clones, of SHA-256 repositories, or of repositories whose configuration Reveille declines
to follow, gave a table of `not_read` rows and exit 0. Exit 0 is the affirmative answer. A script
or an agent that checks only the exit code, which is what the contract asks it to do, read
"these repositories were assessed" when none had been.

The exit codes follow `grep` and `diff`: 0 an affirmative answer, 1 a negative answer, 2 could
not run. With nothing read, there is no answer about any repository to give, affirmative or
negative.

## Decision

**When `repos` found at least one repository and could read none of them, it exits 2. The rows are
still written to stdout, in the format asked for, and one error on stderr says that none could be
read.**

- **One row read keeps exit 0.** A repository with no commits (`empty`) was read, and counts.
- **The rows are still given** because each says why its repository was not read, and that is
  what the caller needs to act on. A caller that treats exit 2 as "discard stdout" loses nothing it
  could rely on.
- **No repository found** stays exit 1, the negative answer ("there are none here").
- **A reader that stops early** does not turn the run into exit 0, as it does for an answer; the
  exit still says that nothing was read.

## Consequences

- An exit code of 0 from `repos` now means at least one repository was read. It still does not
  mean all were: the rows, and the `not_read` count in the totals, say which were not.
- A pipeline that ran `repos` over a directory where every repository is refused, and relied on
  exit 0, now fails. That pipeline was reading an empty assessment as a real one.
- Exit 2 is no longer "nothing on stdout" for `repos`. Other commands are unchanged.
