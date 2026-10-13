# 0024 — The state of a repository now: `reveille state`

**Status:** Proposed (2026-10-12).

## Context

A developer coming back to a repository, or an assistant starting a session, first asks where
things stand: which branch, anything half-done (a merge or rebase stopped on a conflict), what is
staged or modified, what is stashed, which worktrees exist, how far the branch is from its
upstream, and what has happened since the last release. Today that is six or seven Git commands
(`status`, `branch -vv`, `log`, `worktree list`, `stash list`, a look inside `.git` for a rebase,
`describe`), each with unbounded output.

Two of them are not passive. Measured on 2026-10-12 (Git 2.55) in a scratch repository:

- **`git status` rewrites `.git/index`** when it finds stale file stat data (index hash changed
  after `touch` and a plain `git status`); `git --no-optional-locks status` left it identical.
- **`git status` runs the program a repository's own `core.fsmonitor` names** (a script set there
  ran); with `-c core.fsmonitor=false` it did not.
- **`git status` runs a content filter** (`clean`, or `process`) that the repository's
  `.gitattributes` assigns and its config defines, to compare a file whose stat data changed.
  Overriding that driver for the call (`clean=cat`, `smudge=cat`, `process=` empty,
  `required=false`) stopped it. History reads (`log --numstat`, `--name-status`) did not start a
  `textconv` driver.

So running Git by hand changes Git data and can run code the repository chose.

## Decision

**A new command, `reveille state`, that reports the repository's present state in one bounded
answer, changing nothing and running nothing.**

- **What it says:** the current branch or a detached commit; its upstream and ahead/behind as of
  the last fetch (stated as such; Reveille never fetches); an operation in progress (merge,
  rebase, cherry-pick, revert, bisect) found from the Git directory's own files; conflicted paths;
  staged, modified, deleted, renamed and untracked counts with bounded path lists; the number of
  stashes; the worktrees (path, branch or detached, locked, prunable); local branches as counts
  (total, merged into the current branch, no commit in 90 days); the latest tag reachable and the
  commits since it, so the next call can be `reveille brief --from <tag>`; the last commit's hash
  and date; shallow-clone and replaced-history flags.
- **Names nobody.** No author, and no branch names other than the current one and the
  worktrees' (branch names can name people; ADR 0022, `05-` research). Paths are listed because
  they are what the reader acts on; they are bounded by `--limit` (default 10).
- **Changes nothing, runs nothing:** every Git call runs with `GIT_OPTIONAL_LOCKS=0` and
  `core.fsmonitor=false`, submodule summaries off. Content filters the repository's own config
  defines (local or worktree scope, found with `git config --show-scope`) are overridden for the
  status call and named in the answer; a filter in the user's global or system config runs as
  they set it. If Git cannot report scopes, or a filter's name holds `=` (which `git -c` cannot
  name), no file is compared. Tests assert the index is
  byte-identical, and that neither an fsmonitor program nor a repository's filter runs; each
  fails with its pin removed.
- **Output:** text under 2 KB and `--format json` (`"document": "state"`). Exit 0 when it ran,
  2 when it could not; there is no negative answer. Reads no `reveille.toml`, like `summary`.

## Alternatives considered

- **Shell out to `git status` and print it.** Rejected: it writes the index and can run
  fsmonitor, and its output is unbounded.
- **Fold it into `summary`.** Rejected: `summary` describes history over a window; this describes
  the working tree now. One command, one question.
- **List every branch by name with its age.** Rejected for the default: branch names often carry
  people's handles. Counts answer "is there clutter?"; `git branch` names them when asked.
- **Fetch to make ahead/behind current.** Rejected: no network (ADR 0006, 0019). The answer says
  "as of the last fetch".

## Consequences

- **Git reads file contents** to compare the working tree with the index; Reveille receives
  paths and status letters only, as for line counts (COMPLIANCE wording).
- **A file a repository-defined filter covers may show as modified**, because it is compared
  unfiltered. Correctness gives way to not running the repository's program, and the answer says
  which filters were not run.
- **Paths on the user's machine appear** (worktree paths, changed files). The answer describes
  the user's own checkout; the docs say so before anyone pastes it elsewhere.
- **The pins apply to every read**, not only this command: no behaviour change for history reads,
  and the "never changes Git data" claim no longer depends on which command ran.
- **Schema 1.2** gains a document type, as `brief` did; no existing field changes.
