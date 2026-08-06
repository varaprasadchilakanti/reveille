# 0004 — History is read in a single `git log --numstat` pass

**Status:** Accepted

## Context

Reveille needs per-commit line additions and deletions. The obvious
GitPython route is to iterate commits and read `Commit.stats`.

`Commit.stats` shells out to `git diff` **once per commit**. The process
spawn dominates, so cost grows linearly with history and is roughly
constant per commit regardless of how small the change is. Measured on
this repository: **7.2 ms per commit** — about six minutes for a
50,000-commit repository, which is an ordinary size.

That put a hard ceiling on what Reveille could be pointed at.

## Decision

`read_commits` runs a single `git log --numstat` with an ASCII
record/field-separated format (`\x1e` between records, `\x1f` between
fields) and parses the stream.

Separator characters are chosen because `\x1e` and `\x1f` cannot occur
in a name, an email, or a SHA, so no quoting or escaping is needed and
no author can break the parse with a crafted name.

## Consequences

Measured **0.77 ms per commit** — 9.4× faster; the same 50,000-commit
repository drops from roughly six minutes to under forty seconds.

Correctness was verified before the change landed, not assumed: output
was compared byte-for-byte against `Commit.stats` across all 180 commits
of this repository and all 5 fixture commits. That comparison surfaced a
pre-existing error in a fixture's own docstring, which had been wrong
for the life of the fixture.

The cost is that Reveille now owns a parser. Text-format changes in
`git log` are a compatibility surface that `Commit.stats` would have
absorbed, and binary files (which `--numstat` reports as `-`) need
explicit handling. Both are covered by unit tests over the parsing
helpers.

**This does not make ownership metrics cheap.** `--numstat` gives
*churn* — lines added and removed per commit. A true bus factor needs
*ownership*, which requires `git blame` per file, measured at ~12.5 ms
per file. On a 10,000-file repository that is minutes, not seconds. See
[0005](0005-commit-concentration-not-bus-factor.md).
