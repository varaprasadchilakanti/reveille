# 0030 — `repos` reads a `.git` link, and gives a used Git directory no row of its own

**Status:** Proposed (2026-10-19). Supersedes, in
[ADR 0026](0026-many-repositories-one-row-each.md), what counts as a working tree; how far the
search goes, and that it follows no link, stand.

## Context

ADR 0026 counts as a working tree a directory holding `.git`, and as a bare repository one
holding `HEAD`, `objects` and `refs`. It follows no symbolic link, so that the search stays
inside the directory given. Two layouts gave the wrong rows, measured with Git 2.55 on
2026-10-19:

- **A working tree whose `.git` is a symbolic link** had no row. `summary`, `state` and the other
  single-repository commands read it, as Git does. The search had treated the link as one it must
  not follow. But a `.git` link is not searched: it names the repository's own Git directory, as
  the `.git` file of a linked worktree does, and those were already rows.
- **The Git directory that `git init --separate-git-dir` makes**, when it lies in the directory
  searched, has `HEAD`, `objects` and `refs`, so it was a second row beside its working tree. Its
  configuration does not say it is bare, so Git cannot open it alone, and the row read "not
  read" with Git's raw "not a git repository".

## Decision

- **A `.git` that is a symbolic link makes a working tree, as a `.git` file does.** The link is not
  entered by the search. Reading the repository reads its Git directory wherever that is, as it
  already did for a `.git` file.
- **A Git directory that a working tree found in the same search uses is not a row of its own.**
  "Uses" is read from files alone, with no Git command: a `.git` directory is its own, a link is
  resolved, and a `.git` file's `gitdir:` line is read (opened without waiting, at most 4,096 bytes).
- **A Git directory that nothing found uses keeps its row**, and its reason says what it is: it
  holds a Git directory but no working tree, and is not configured as bare. The same message
  replaces Git's raw one when the single-repository commands are pointed at it.

## Consequences

- One repository, one row, in both layouts. A store left behind after its working tree moved is
  still listed, and says why it cannot be read, so nothing is dropped without a word.
- The search still enters no link. The Git directory a link or a `.git` file names may lie outside
  the directory searched, and that was already true for linked worktrees.
- Deciding "uses" without Git means a `gitdir:` line Git would read differently (a path with
  trailing spaces, say) may leave a store with its own row. The row then says why it was not read.
