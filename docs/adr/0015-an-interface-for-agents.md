# 0015 — An interface for agents: summary, who-changed, stdout and bounded lists

**Status:** Accepted (2026-10-09)

## Context

Calls to Reveille from AI assistants acting for a person are expected, and the author asked the
assistant building it whether it would use the tool itself. Measured when this was written
(October 2026) on llama.cpp (9,015 commits,
1,682 identities), it would not, for two of its two common questions:

- **"Is this project active, and how concentrated?"** `generate --format json` took 10 seconds and
  wrote 663 KB — about 166,000 tokens, mostly 1,682 contributor rows. The figures that answer the
  question (`derived`) are about 200 bytes. An assistant reading the file fills its context; one
  that does not must know to look only at `derived`.
- **"A bug appeared here; who should I ask?"** There is no path argument. `git log -- <path>`
  answers in well under a second, so the assistant uses Git.

What Reveille does that `git log` does not is real — merges excluded, identities resolved through
`.mailmap` and noreply folding, scrubbed strings, windows that do not count time before a
repository existed, shallow clones and wrong clocks declared, figures computed rather than
estimated, and output that can be reproduced. It reaches an assistant in a shape that costs more
than it saves.

## Decision

Four additions, each small, each built on what exists.

- **`reveille summary`** — the repository in about 2 KB: window, totals, concentration,
  Gini, quiet run, the findings, and the provenance an answer must carry (analysed commit, shallow
  clone, commits dated after the window, co-authored commits). **It names no contributor.** It does print
  the repository and branch names as they are, which can name someone, and with one or two
  people its figures describe identifiable individuals, so it is the smallest default, not an
  anonymous one. It reads no line counts, which are the expensive part of a
  run, so it is fast.
- **`reveille who-changed <path>`** — for one file or directory: commits, authors, when it was last
  changed, the authors alphabetically, and the five who changed it most recently, alphabetically,
  by the rules of ADR 0013 (no count or date per person; automated accounts apart). It names
  people; running the command is the request, as `--area-authors` is for the report. The path is
  taken literally (a `:(literal)` pathspec, after `--`), so it cannot be an option or pathspec
  magic. No line counts are read. Renames are not followed: a file's history before a rename
  belongs to its old path, as `git log -- <path>` without `--follow` reports it.
- **`--output -`** writes the report, in any format, to stdout, and nothing else goes there:
  progress, notes and errors are on stderr.
- **`--limit N`** bounds every list of people in JSON and CSV (`generate`) and in `who-changed`;
  `summary` lists no people and takes no limit. In JSON the full count and a
  `truncated` flag sit beside each bounded list; a CSV has nowhere to put them, so a cut CSV
  is announced on stderr. Off unless given, so the existing contract holds;
  `summary` and `who-changed` are bounded by default.

Exit codes keep their meaning: 0 answered, 1 answered negatively (no commits in the window or on
the path), 2 could not run.

## Consequences

**An assistant's default path is small and names no contributor.** `capabilities` and `llms.txt` point to
`summary` first, to `who-changed` for "whom do I ask", and to `generate` for the full report.

**Two more commands to maintain.** Both reuse the reader, the domain functions and the output
rules already tested; neither adds a dependency.

**`who-changed` answers less than `git log -- <path>` can.** It gives no per-commit detail, by
design; an assistant that needs the commits should read them with Git. What it adds is the
resolution of identities and the rules about how people are named.

**`schema_version` stays `1.1`** while 0.9.0 is untagged: every addition is additive. The summary
and who-changed documents carry the same `schema_version` and a `document` field naming which
document they are.
