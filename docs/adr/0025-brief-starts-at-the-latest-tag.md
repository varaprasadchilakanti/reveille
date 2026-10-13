# 0025 — `brief` starts at the latest tag when no point is given

**Status:** Proposed (2026-10-13). Partly supersedes ADR 0022 (its "exactly one of").

## Context

ADR 0022 required exactly one of `--from <revision>` or `--since <date>`. The most common question
is "what changed since the last release", so a caller had to run `state` or `git describe` first to
learn the tag, then call `brief`.

## Decision

With neither option, `brief` starts at the nearest tag reachable from the analysed branch
(`git describe --tags --abbrev=0`), and the answer names it as the point, exactly as
`--from <tag>` would. With no reachable tag it cannot run (exit 2) and says to give `--from` or
`--since`. Giving both is still refused.

## Consequences

- One call answers "what changed since the last release".
- The point is chosen by the repository's tags, not by the caller. The output always names it, so
  the choice is visible.
- A lightweight tag counts as a tag, as it does for `git describe --tags`.
