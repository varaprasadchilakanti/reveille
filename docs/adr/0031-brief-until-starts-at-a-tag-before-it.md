# 0031 — `brief --until` starts at the latest tag on or before that day

**Status:** Accepted (2026-10-23). Proposed 2026-10-23. Partly supersedes ADR 0025 (which tag, when `--until` is given).

## Context

ADR 0025 starts a brief given neither `--from` nor `--since` at the nearest tag reachable from the
analysed branch. With `--until`, that tag can be later than the window's end: with `v1` in January
and `v2` in March, `brief --until 2026-02-01` started at `v2` and asked for the commits after March
up to February. It answered "No commits since v2", a negative that describes no period anyone
asked about.

## Decision

With `--until` and neither `--from` nor `--since`, `brief` starts at the nearest tag reachable from
the newest commit on the branch dated (UTC) on or before the `--until` day: `git rev-list -1
--before=<the next day>` then `git describe --tags --abbrev=0` from that commit. With no such tag
it cannot run (exit 2) and says there is no tag on or before that day. Without `--until`, ADR 0025
is unchanged.

## Consequences

- "What changed in the release before this date" is one call.
- The choice depends on commit dates, which a wrong clock or a rebase can make out of order; the
  answer names the tag it started at, so the choice is visible.
- One more Git call when `--until` is given. It was measured not to write into the Git directory,
  nor to start `core.fsmonitor`, `gpg.program` (with `log.showSignature`) or a hook
  (`tests/integration/test_brief_tag_before_until.py`, Git 2.55).
