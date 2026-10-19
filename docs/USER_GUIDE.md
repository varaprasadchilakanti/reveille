# Reveille: User Guide

Every option, every report section, and what a report contains about people.
Install and first run: [README](../README.md).

---

## Contents

- [How Reveille Works](#how-reveille-works)
- [Commands and Outputs](#commands-and-outputs)
- [Exit Codes](#exit-codes)
- [The reveille capabilities Command](#the-reveille-capabilities-command)
- [Starting a Session, and the reveille skill Command](#starting-a-session-and-the-reveille-skill-command)
- [Structured Output](#structured-output)
- [The reveille init Command](#the-reveille-init-command)
- [TOML Configuration Reference](#toml-configuration-reference)
- [Understanding the Report](#understanding-the-report)
- [What the Report Contains About People](#what-the-report-contains-about-people)
- [Before You Share a Report](#before-you-share-a-report)
- [The Ranking Algorithm](#the-ranking-algorithm)
- [Practical Patterns](#practical-patterns)
- [Troubleshooting and Questions](#troubleshooting-and-questions)

---

## How Reveille Works

**Reading.** Reveille opens the repository and reads the commit log for the branch and date
range in one `git log --numstat` pass, beside a `git rev-list` that authenticates each record and
a second `git log` that reads only `Co-authored-by` trailers. The read scales with commits, not
with changed files. Measured 2026-10-12, Reveille 0.9.0, Git 2.55, warm cache, one 20-core
machine: on llama.cpp (9,015 commits) `generate --format json` took 9.35 s and `summary`, which
skips the line counts, 1.02 s; on git.git (61,112 commits), 22.6 s and 2.58 s.

**Merge commits are excluded.** A merge repeats work already counted in the commits it joins, and
counting it would credit whoever merged. A change made only in a merge, such as a conflict
resolution, is not counted either. Counts are therefore lower than raw `git log`, by the number the
full JSON's `provenance.merge_commits_excluded` and the summary's `repository.merge_commits_excluded`
give: the merges in the branch and window, whoever made them (`--exclude-author` does not change
it). The summary text says it when it is not zero.

**Writing.** Reveille never changes the repository's Git data (history, refs, index, objects or
configuration), and any output path inside `.git` is refused. It writes one file: the report.

**Identity.** A contributor is keyed on author email, not display name, so someone who committed
under two names is one person, shown under the name from their latest commit. If a `.mailmap` is
present at the repository root (in a bare repository, the one committed at `HEAD`), addresses are
resolved to the canonical identity before aggregation. All four forms in `gitmailmap(5)` are
supported with Git's own precedence: name and email, then email alone, then name alone. Matching
is case-insensitive and malformed lines are skipped silently, as Git does, so a `.mailmap` that
works with `git shortlog` works here. `reveille init --mailmap` writes an annotated template.

GitHub noreply addresses are folded on the account number, which stays with the account when its username changes:
`12345678+old@...` and `12345678+new@...` are one contributor, shown under the newer username. A
legacy `username@users.noreply.github.com` joins that account only when one account in the
history used the username; when two did, it stays apart rather than merge two people
([ADR 0023](adr/0023-noreply-addresses-fold-on-the-account-number.md)). They are not folded into
your configured address, so a commit made through the GitHub web interface can still read as a
second person until a `.mailmap` says otherwise.

**Rendering.** Derived measures are computed, and with `--ranking` contributors are scored
([The Ranking Algorithm](#the-ranking-algorithm)). One HTML file is written with all JavaScript and
chart data embedded; it opens offline in any modern browser.

---

## Commands and Outputs

Every command can also be run as `reile` (a shorter name for the same program) or as
`python -m reveille`.

`state`, `brief` and `summary` also take `--format markdown`, to paste into an issue, a pull request
or a CI job summary. Paths, branch and tag names are put in code spans, with newlines
shown as `\n`, so a name cannot add a heading, a link or HTML.

`state` and `brief` also take `--format line`: one line of counts, for a shell prompt or a status
bar, such as `reveille: main 1a2b3c4; 1 staged, 2 untracked; 1 stash; v1.0 +3`. It lists no path and no
author, carries no notice, and a newline in a name is shown as `\n`.

`reveille generate` takes the options below. `summary`, `brief`, `state`, `who-changed`, `repos`,
`init`, `validate` and `capabilities` are described after the table; each of their options is listed with its command.

| Option | Default | Meaning |
|---|---|---|
| `--repo`, `-r` | `.` | A working tree or any directory inside it (the search stops at `GIT_CEILING_DIRECTORIES`, as Git's does; with `GIT_DIR` or `GIT_WORK_TREE` set, as in a Git hook, give the root; those variables, `GIT_INDEX_FILE` and `GIT_OBJECT_DIRECTORY` do not change what is read), or a bare repository (which needs `--output`: its root is Git's own directory, where Reveille does not write). |
| `--output`, `-o` | `reveille-report.html` in the repository root | See [Output path](#output-path). |
| `--since`, `--until` | first commit; today (UTC) | Inclusive dates, `YYYY-MM-DD`. See [The window](#the-window). |
| `--branch`, `-b` | the checked-out branch | Commits reachable from this branch. The checked-out branch is not necessarily the default branch. |
| `--exclude-author` | none | Removes a person. Repeatable. See [below](#--exclude-author). |
| `--exclude-path` | none | Leaves a path out of every figure. Repeatable. See [below](#--exclude-path). |
| `--hide-emails` | off | Replaces people's email addresses with per-report tokens. See [below](#--hide-emails). |
| `--min-commits` | `1` | Lists only contributors with at least this many commits. See [below](#--min-commits). |
| `--title` | repository name | The report's title. |
| `--ranking`, `--no-ranking` | ranking off | See [Ranking](#--ranking-and---no-ranking). |
| `--area-authors`, `--area-depth` | off; `3` | See [Who changed each area](#--area-authors-and---area-depth). |
| `--limit` | every one | See [below](#--limit). |
| `--format` | `html` | `html`, `json` or `csv`. See [Structured Output](#structured-output). |
| `--deterministic` | off | See [below](#--deterministic). |
| `--config`, `-c` | `reveille.toml` in the current directory, if present | A TOML file; flags win over it. A discovered file is announced on stderr. See [TOML Configuration Reference](#toml-configuration-reference). |
| `--verbose` | off | DEBUG diagnostics on stderr; the report is unchanged. |
| `--quiet`, `-q` | off | No progress lines on stderr. Notes, warnings and errors are still written. |

`--help` (`-h`) works on every command. `reveille --version` (or `-v`) prints the version. It is a
flag, not a command: `reveille version` exits 2.

### Output path

The parent directory must exist. A path inside the Git directory, a path containing `..`, and a
directory are refused (exit 2). The default path is inside the working tree, untracked, so
`git add -A` would commit it; add it to `.gitignore` or choose another path. On POSIX systems a new
report is readable and writable by its owner only (mode 600, tested on Linux), because it names
people; a report written over an existing file keeps that file's permissions. A path outside the
repository given with `--output` is written, with a warning on stderr; the same path set in `reveille.toml` is refused, because a configuration
file is found automatically and may come from a repository you do not control. A bare repository
needs an explicit path.

`--output -` writes the report to stdout, in any format, and nothing else goes there: progress,
notes and errors are on stderr. CSV on stdout carries no byte-order mark.

```bash
reveille generate --format json --output - | jq .derived
```

JSON and CSV are written at the `--output` stem with a `.json` or `.csv` extension.

### The window

`--since` and `--until` are inclusive. Without `--since` the window starts at the first commit;
an earlier `--since` changes nothing, because days before a repository existed are not quiet days.
Without `--until` it ends today (UTC), and a commit dated after today (a wrong clock, or a rebase
that kept a future date) is counted in no figure: the header and a note on stderr say how many,
and a later `--until` includes them. With `--deterministic` the window closes on the last commit
instead. Git reads dates only from 1970 through 2099: an earlier `--since` or a later `--until` is
no limit, and a later `--since` is read as 2099-12-31, after which only a commit with a wrong clock
can fall.

A commit's date is its commit date (Git's committer date), not the date it was first written: a
rebase, an amend or a cherry-pick places the commit on the day it was rewritten.

In a shallow clone, which CI checkouts are by default, only the history the clone holds is
analysed, and the header and stderr say so. `git fetch --unshallow` fetches the rest.

### `--exclude-author`

Excludes a person by name or email. Case, runs of spaces, Unicode normalisation form and invisible
format characters (such as a zero-width joiner) are ignored in the comparison, and a GitHub noreply
address in either form (`123+name@` or `name@`) names the account, the legacy form only when one
account in the history used that name. An identity is its address, so every commit made under an
address that the value matched anywhere in the branch's history (not only in the window) is
removed, whatever name it carries, as is every address a `.mailmap` ties to it. A name that reaches
several addresses removes them all, and stderr names the addresses so you can give one instead. A
value that matches nothing is reported on stderr. See
[ADR 0020](adr/0020-exclude-author-removes-a-person-by-address.md).

```bash
reveille generate --exclude-author "dependabot[bot]" --exclude-author "release-bot@example.com"
```

Accounts with `[bot]` in the name or address are already kept out of the people figures (see
[Summary cards](#summary-cards)); excluding one removes its commits from every figure too.

### `--exclude-path`

Leaves a file or directory out of every figure: commits, lines, hotspots, file types and areas.
The path is relative to the repository root, whichever directory you run from, and is matched
literally: `*.md` is a file of that name, not a pattern. A directory takes everything under it.
A commit that changed only excluded paths is not counted at all; a commit that also changed
something else is counted, without the excluded lines. A path no commit on the branch ever
changed is reported on stderr, since it is almost always a typo. The paths are stated in the
report header, the summary and the JSON `provenance.filters.exclude_paths`. `generate`,
`summary` and `brief` accept it; in `reveille.toml` it is `[filters] exclude_paths`.

```bash
reveille generate --exclude-path vendor --exclude-path docs/generated
```

### `--hide-emails`

Replaces people's email addresses in the report with a token, `contributor-1@hidden.invalid`,
`contributor-2@hidden.invalid` and so on, numbered in the order the contributor table lists people.
It covers authors, co-authors, people below `--min-commits`, area authors, the data the charts are
drawn from, an address written into a name (shown as `(address hidden)`), and the login in an SSH
remote (`jane@host:group/repo` becomes `host:group/repo`). An address in the branch name, the
repository's directory name or the remote's path is shown as `(address hidden)` too
(`user/jane@example.com` becomes `user/(address hidden)`), and so is one with an IP address for
its domain (`bob@[10.1.2.3]`). A remote that is a path on your machine keeps only its last part
(`/home/jane/clients/acme.git` becomes `acme.git`), since the rest names your directories, and
so does a network share (`\\server\home\jane\acme.git`); an `ext::` remote, a command line,
becomes `ext::(command hidden)`. The at sign is recognised written plainly, fullwidth (`＠`), small
(`﹫`) or as `%40`, and in a name with spaces around it, which can hide a little more than the
address. Addresses are found by pattern, and no pattern knows every way of writing one: read the
report before you share it. The HTML table then shows names only;
JSON and CSV carry the tokens, and `provenance.emails_hidden` is `true`.

File paths are not changed: the extension and generated-file figures are read from them, so a
file or directory named after an address (`users/jane@example.com/`) stays in the report as it
is. Check the file sections before sharing a report of such a repository.

The "Third-party licences" section at the end of every HTML report is not changed either. It
carries the copyright notices of the chart library and the packages it bundles as their authors
published them, and those include the names and email addresses of some of those authors. They
are about the library, not about your repository, and their licences require them in every copy.

A token is a number, not derived from the address, so it cannot be reversed by trying addresses,
and `.invalid` is a domain that can never receive mail. Tokens mean nothing across reports: the
same person can have a different number in another report. An automated account keeps its `[bot]`
marker, so every figure is the same as without the option. Names are not changed; to keep a person
out of the report entirely, use `--exclude-author`. In `reveille.toml` it is `[report]
hide_emails = true`.

```bash
reveille generate --hide-emails --output shared-report.html
```

### `--min-commits`

Chooses who is *listed*, not who is counted: every figure still describes everyone, and the
header says how many are listed
([ADR 0011](adr/0011-filters-choose-the-listing-not-the-analysis.md)). It is not a privacy control.

### `--limit`

Bounds every list of people in JSON and CSV to this many. JSON states the full total and a
`truncated` flag beside each list; a cut CSV is announced on stderr. It shortens lists for
assistants and scripts and removes nobody from the figures. `who-changed` accepts it too (default
20). In `reveille.toml` it is `[report] limit`.

### `--ranking` and `--no-ranking`

Ranking is **off by default**; `--ranking` turns it on. If both flags are given, `--no-ranking`
wins. With ranking off the report
omits the scored table, and the JSON omits `tier`, `tier_designation`, `composite_score` and
`percentile` entirely rather than emitting placeholders: a key reading `"tier": 0` is a number a
consumer can mistake for data. Check `provenance.ranking.enabled` to know which shape you have.
Everything else stays, including `rank` in JSON and CSV, which is table order (by commits; by score with `--ranking`).

It is off because it scores and tiers named individuals on the volume and regularity of commits
and nothing else ([ADR 0010](adr/0010-ranking-is-opt-in.md); [The Ranking
Algorithm](#the-ranking-algorithm)). In `reveille.toml`, `[ranking] enabled = true` must be a real
boolean: `enabled = "false"` is a string and is rejected.

### `--area-authors` and `--area-depth`

**Off by default**, because it names people, organised by directory, and `--ranking` does not
switch it on ([ADR 0013](adr/0013-who-changes-what-is-opt-in-and-area-first.md)).
`--area-authors` adds the section *Who Changed Each Area* ([details](#who-changed-each-area)).
An area is a directory of at most `--area-depth` components (default 3, so `src/app/core` rather
than `src/app`); a file in a shallower directory belongs to that directory, and top-level files
form the area `(root)`. Generated lock files are left out.

```bash
reveille generate --area-authors --area-depth 2
```

### `--deterministic`

Two runs over an unchanged repository give identical bytes, in every format, on the same Reveille
version, installed dependencies and Git settings. Git settings matter because some change the
counts Git reports. Reveille pins the ones measured to do so to Git's defaults on every read, so a
repository's own `.git/config`, or yours, cannot change them: `diff.algorithm` (another algorithm
moved line counts), `diff.renames` (off, a renamed file counts as deleted and added),
`core.bigFileThreshold` (a low value turns large files into binary, counted as no lines),
`log.showRoot` (off, the first commit's lines vanish) and `trailer.separators` (another separator
hides `Co-authored-by` trailers). Settings that could make a read start a program or wait for
ever, such as `core.fsmonitor`, `log.showSignature` or `diff.orderFile`, are pinned off too.
Other settings are not pinned.

It pins `generated_at` to the analysed commit's timestamp instead of the clock (the idea behind
`SOURCE_DATE_EPOCH`), and closes the analysis window on the last commit instead of today.
**The second part changes the numbers, not only the bytes**: the ranking's recency component is
measured against the window, so pinning the window pins the scores. That is why the flag is
opt-in, and why `provenance.deterministic` records its use. Use it when a report must be
re-checkable: attached to an audit, committed beside a release, or compared with an earlier run.

### `reveille summary`

The repository in a few lines, naming no contributor: window, commit and people counts, Gini,
longest quiet run, the written findings and a notice that the figures need checking.
`--format json` adds commit concentration and days since the last commit. It reads no line counts
and no `reveille.toml`. Options: `--repo`, `--since`, `--until`, `--branch`, `--exclude-author`,
`--exclude-path`, `--deterministic`, `--verbose` and `--format text|json|markdown` (default `text`).

```bash
reveille summary --format json
```

It is the starting point for an assistant: under 1 KB as text and about 2 KB as JSON. It carries
no contributor name or address, but it does carry the repository and branch names, which can name
someone, and with one or two people its counts can identify someone. Check it before sending it to a
hosted model.

### `reveille state`

```bash
reveille state
reveille state --format json --limit 20
```

Where the repository stands now, in one bounded answer: the branch or detached commit; its
upstream and how far ahead or behind, as of the last fetch (Reveille never fetches); a merge,
rebase, `git am`, cherry-pick, revert or bisect stopped part-way; conflicted paths; what is
staged, modified, deleted, renamed and untracked, with lists bounded by `--limit` (default 10);
stashes; worktrees; local branches as counts (total, merged into the current commit, no commit in
90 days before it); and the latest tag with the commits since, so the next call can be
`reveille brief --from <tag>`. Options: `--repo`, `--limit`, `--verbose`,
`--format text|json|markdown|line`.

It makes no outbound call. It runs Git with signature checking, fsmonitor and repository-defined
content filters switched off. A plain `git status` rewrites `.git/index` when file stat data is
stale, and runs the programs a repository's own config names as `core.fsmonitor` or as a content
filter; Reveille switches all three off, and tests check each. A filter from your own global config
runs as you set it; one the repository defines does not, so files it covers may show as modified,
and the answer says so. It names no author. It lists local paths (changed files and worktree
directories, which can contain your login name), the current branch, its upstream, the branches checked out in worktrees and the latest tag; no
other branch is named. Branch, directory and tag names are printed as they are.

### `reveille brief`

```bash
reveille brief --from v0.9.0
reveille brief --since 2026-10-01 --format json
```

What changed since a point, in counts. Give `--from <revision>` (a tag, branch or commit, read by
ancestry as `git log <revision>..<branch>` is) or `--since <date>`; with neither, it starts at the
latest tag reachable on the branch and names it, and with no tag it stops with exit 2. Other
options: `--repo`, `--branch`, `--until`, `--exclude-author`, `--exclude-path`, `--deterministic`, `--limit`
(default 5), `--verbose` and `--format text|json|markdown|line`.

It states commits (merges excluded), people and automated accounts as counts, commits crediting a
co-author, the most changed areas (directories three deep) and file types, files added, areas
changed after 90 or more days without a commit, and tags whose commit lies in the range. It names
nobody, gives no line counts and no measure of a period (no Gini or quiet run), and ends with the
commit it reached: `reveille brief --from <that commit>` next time gives what changed since. A
revision that is not an ancestor of the branch is allowed and stated. Between two commits the
answer depends on nothing else, so it is reproducible without `--deterministic`.

Area paths and tag names come from the repository and can name people (`users/jsmith/`). With one
or two people, the counts can identify someone: "1 person" identifies them to a team that knows who
it was.

On llama.cpp, from its oldest tag (8,928 commits), it took about 2 seconds and printed 672 bytes
(measured 2026-10-12, Git 2.55, warm cache, one 20-core machine).

### `reveille who-changed`

```bash
reveille who-changed src/parser/lexer.c --since 2026-01-01
```

Takes a path (literal, inside the repository; relative to the current directory when you run it
inside the repository, else to the repository's root) and the options of `summary` except
`--exclude-path` and `--format markdown`, plus `--limit` (default 20). The answer lists the path's authors alphabetically, the five who
changed it most recently (the people to ask first), automated accounts and co-authors apart, and
when the path was last changed. It gives no count or date per person: who changed a file is a
fact the history records, and "who did the most" is not what this is for. It says who changed the
code, not who knows or owns it. It reads only the commits that changed the path, and no line
counts. A path that no commit in the window changed is a negative answer (exit 1). Renames are
not followed: history from before a rename belongs to the old path.

### `reveille repos`

```bash
reveille repos ~/src
reveille repos /srv/mirrors --depth 2 --format csv > repositories.csv
```

Finds the Git repositories in a directory and gives one row per repository: its path, branch, the
date of the last non-merge commit and the days since, and the commits, people and automated
accounts in the window (the last 90 days to today, UTC; `--days` and `--until` change it), with a
status by fixed rules: **active** with a commit in the window, **quiet** with one in the last 365
days, **dormant** beyond that, **empty** with no commit (or none left after `--exclude-author`).
The rules are stated in every format ([ADR 0026](adr/0026-many-repositories-one-row-each.md)).

- **What counts as a repository:** a directory holding `.git`, or a bare repository (`HEAD`,
  `objects` and `refs`), so a folder of server-side mirrors works. The search goes one level down
  by default and at most three (`--depth`); a repository found is not searched inside, so a
  submodule or a nested clone is not a row; a symbolic link is not followed.
- **Each repository is read as `summary` reads one**, with its `.mailmap`, `--exclude-author`
  applied in every repository, and no line counts. A value that matched nothing in any repository
  is reported once on stderr.
- **A repository that cannot be read** (a partial clone, a SHA-256 repository, a corrupt one) is a
  row with status `not_read` and the reason; the others are still read, and the exit code is 0.
  No repository found is a negative answer (exit 1).
- **It names nobody and counts nobody across repositories.** The people column describes one
  repository each; adding it up does not give a number of people.
- **Formats:** `text` (default), `json`, `markdown` and `csv`. CSV cells that a spreadsheet would
  read as a formula are prefixed with `'`. Paths are relative to the directory given; the JSON
  carries the directory's name, not its full path, but a path can still hold a login name.

### `reveille validate`

```bash
reveille validate --repo /path/to/repository
```

Exits 0 if the path is a readable Git repository with at least one commit, 1 if it has none, 2 if
it cannot be read. Options: `--repo` and `--verbose`. It takes no date options.

### Co-authors

A `Co-authored-by: Name <address>` trailer credits another author. Reveille reads those trailers
(and nothing else in a commit message) and reports them beside authorship, never inside it: each
contributor's co-authored count, a line naming identities credited only as co-authors, and a
finding with the number of commits that credit one. Charts and authorship figures count authors
only. A trailer is written by whoever wrote the commit and is not verified
([ADR 0014](adr/0014-co-authors-are-a-separate-fact.md)).

---

## Exit Codes

Every command returns one of three codes. The numbers will not change without a major version
bump.

| Code | Meaning | When |
|---|---|---|
| `0` | Success | The command ran and its answer is affirmative. |
| `1` | Negative answer | Reveille ran correctly and the state does not satisfy the request: the analysis window has no commits, or the repository has none. |
| `2` | Could not run | An invalid flag value, malformed configuration, a path that is not a readable Git repository (including one Git refuses because another user owns it, and a SHA-256 repository), an output location that cannot be written, or an error Reveille did not anticipate. |

Script against the difference between `1` and `2`. A negative answer may be an acceptable state to
record (a new repository has nothing to report); an inability to run is a broken pipeline step.

```bash
reveille validate --repo ./service
case $? in
  0) echo "has commits, proceeding" ;;
  1) echo "no commits in range - skipping report" ;;
  2) echo "misconfigured, failing the build" >&2; exit 1 ;;
esac
```

Further detail goes to stderr, not into more exit codes, which would break scripts that branch on
the existing ones.

With `--format json`, `summary`, `brief`, `state`, `who-changed`, `repos` and `capabilities`
write each stderr message as one JSON object per line, `{"level": "error", "message": "..."}`
(levels `error`, `warning` and `note`, and `debug` with `--verbose`), so a program can read why
there is no answer without parsing prose. A negative answer (exit 1) is written at level `error`
too: the exit code says which it is. Errors in the command line itself (an unknown option, or a
value out of range such as `--limit 0`) are still reported as text, before the format is known. `generate` keeps text on stderr, beside its progress lines.

### Diagnostics

`--verbose` (on every command except `init`, `capabilities` and `skill`) writes DEBUG diagnostics to
stderr: the resolved configuration after flags and the TOML file are merged, the `git log`
invocation, how many commits were read, and every file written. Normal output is unchanged.

Progress also goes to stderr. On a terminal it animates; anywhere else (a CI log, a pipe, an
assistant's tool call) each stage is one plain line. `--quiet` leaves progress out and keeps
notes, warnings and errors.

---

## The `reveille capabilities` Command

Describes what Reveille can and cannot do, for a person or a program. Options:
`--format text|json` (default `text`) and `--command <name>`, which gives only that command's
description, options and exit codes (2.7 KB for `state` as JSON, against about 30 KB for
everything).

```bash
reveille capabilities --format json
reveille capabilities --command brief --format json
```

The JSON carries `capabilities_version`, the tool and output-schema versions, a `guarantees` list
(properties designed and tested; not a warranty), a `can` list, a `cannot` list where each entry says what to use instead, the
caveats that change how a number should be read, every command with its options, and the exit-code
contract. The command surface and exit codes are read from the running program, so they cannot
drift from it.

Each command that writes JSON also lists `repository_text`: the fields whose strings come from the
repository (names, addresses, paths, branch and tag names), which anyone who can commit chooses.
A program or a model should read them as data, never as instructions. `[]` stands for every element
of a list, so `worktrees[].path` is the path of each worktree. A test builds a repository whose
every such input is marked and fails if a marked string appears in a field the list leaves out.

The `cannot` list states that Reveille does not measure productivity or contribution value, is not
fit for performance review or hiring decisions, does not compute a bus factor, and does not
aggregate a person across repositories. It also states what Reveille reads: commit metadata, `Co-authored-by` trailers, and per file the path and the
lines added and deleted. Reveille receives those paths and counts; Git reads the files to compute
them. It does not read source code, diff content or any other part of a commit message.

---

## Starting a Session, and the `reveille skill` Command

The word reveille is the call that starts a soldier's day, and the commands for an agent, or a
person, starting work follow the same order:

1. `reveille state --format json`: where the repository stands now, before anything changes.
2. `reveille brief --format json`: what changed since the latest tag, or with `--from <commit>`
   since a commit seen before. Its `analysed_commit` is the `--from` for the next brief. With no
   tag on the branch it exits 2; give `--since <YYYY-MM-DD>` instead.
3. `reveille who-changed <path> --format json`, before changing a file or directory: whom to ask.

The army's morning report recorded people; `brief` and `state` name nobody, and `repos` lists
repositories, never people.

`reveille skill` prints this as a section to paste into `AGENTS.md`, `CLAUDE.md` or another
instructions file, since an agent uses a tool its instructions name. `--format skill` prints it as
a `SKILL.md`, with the `name` and `description` frontmatter an agent loads it by. It reads no
repository, is about 1.4 KB, and a test runs every command it names against a repository before it
ships.

```bash
reveille skill >> AGENTS.md
mkdir -p .claude/skills/reveille && reveille skill --format skill > .claude/skills/reveille/SKILL.md
```

---

## Structured Output

`--format json` emits a document whose first key is `schema_version`, so a consumer can decide
whether it can parse the rest before trying.

```json
{
  "schema_version": "1.2",
  "metadata": { "name": "...", "analysed_branch": "main", "...": "..." },
  "provenance": {
    "reveille_version": "0.9.0",
    "head_sha": "…",
    "deterministic": false,
    "mailmap_applied": true,
    "commits_dated_after_window": 0,
    "shallow_clone": false,
    "...": "...",
    "filters": {
      "requested_branch": "main",
      "requested_since": null,
      "requested_until": null,
      "exclude_authors_count": 0,
      "min_commits": 1
    },
    "ranking": { "enabled": false, "weights": null }
  },
  "contributors": [ "..." ],
  "derived": {
    "commit_concentration": 2,
    "gini_coefficient": 0.46,
    "population_size": 5,
    "contributors_below_threshold": 0,
    "...": "..."
  },
  "notice": "Computed from Git history by fixed rules, offline. History can be incomplete or wrong (rewritten, shallow, misdated, split identities); check before relying on it for a decision."
}
```

- **`schema_version`** changes when the shape changes, not when the tool does. A major bump means
  a removal or a rename; a minor bump means an additive field.
- **`provenance`** records what produced the numbers, so two reports that disagree can be
  reconciled. `metadata.analysis_since` is where the window began; `provenance.filters.requested_since`
  is whether anybody asked for it, which tells "the full history, which starts in March" from
  "filtered to start in March". `exclude_authors_count` is a count, not the values: recording an
  excluded address would put it back in the report.
- **`notice`** is the sentence printed under the HTML header and with every `summary`, so a
  document passed on without the page around it still says what it cannot carry.
- The scoring fields are present only with `--ranking`; `rank` (table order: by commits, or by score with `--ranking`) is
  always present. The raw commit list is not included.

**CSV** is the contributor table alone, UTF-8 with a byte-order mark so Excel reads it correctly.
Columns: `rank`, `name`, `email`, `commits`, `lines_added`, `lines_deleted`, `net_lines`,
`active_days`, `last_commit_date`, `co_authored_commits`. With `--ranking`, `designation`, `tier`,
`composite_score` and `percentile` are added and `rank` is a ranking; without it `rank` is table
order only.

**HTML** is one self-contained file of about 1.7 MB, most of it the embedded chart library (the
plotly.js cartesian bundle, pinned) and its third-party licences, which the report carries in a
collapsed section after its footer: 1.69 MB for a one-commit repository and 1.70 MB for this one
(measured 2026-10-18; 0.9.0's reports were 4.9 MB).

---

## The `reveille init` Command

`reveille init` writes an annotated `reveille.toml` with every key present, commented out and
described. The current
directory must be a repository root; anywhere else it stops with exit 2, even with `--output`.

```bash
reveille init
```

The file has no effect until you uncomment keys. Its structure is the
[TOML Configuration Reference](#toml-configuration-reference). Options:

- **`--output`, `-o`** (default `./reveille.toml`) writes the file elsewhere. The parent directory
  must exist.
- **`--force`** replaces an existing file. Without it, an existing file is an error.
- **`--mailmap`** also writes an annotated `.mailmap` template at the repository root, covering
  all four `gitmailmap(5)` forms with examples and the matching precedence. An
  existing `.mailmap` is left alone with a message; with `--force`, both files are overwritten.

```bash
reveille init --mailmap --force
```

On POSIX systems a new `reveille.toml` or `.mailmap` is readable and writable by its owner only
(mode 600), as a report is, because a filled-in `.mailmap` names people. Git records no read
permissions, so committing, cloning and CI are unaffected. To let other accounts on the same
machine read a shared checkout, run `chmod 644 reveille.toml .mailmap`; `--force` keeps a mode you
set. A `.mailmap` Reveille cannot read is reported on stderr and not applied.

---

## TOML Configuration Reference

For regular runs with the same parameters. Pass the path with `--config`, or
name the file `reveille.toml` in the directory you run from, where it is loaded without being
asked for. That is announced on stderr with every setting applied, because the directory may
belong to someone else. An output path inside the Git directory is refused (exit 2), whether it
comes from the file or a flag. All sections and keys are optional; an absent key takes the
default, and a flag beats the file.

```toml
[report]
title = "Repository Activity — Q4 2024"   # --title
output = "./reports/q4-2024.html"          # --output
branch = "main"                            # --branch
since = "2024-10-01"                       # --since
until = "2024-12-31"                       # --until
limit = 50                                 # --limit
hide_emails = false                        # --hide-emails; a real boolean
# format = "html"                          # --format: html (default), json, csv
deterministic = false                      # --deterministic; a real boolean

[filters]
min_commits = 2                            # --min-commits
exclude_authors = [                        # repeated --exclude-author
    "dependabot[bot]",
    "github-actions[bot]",
]
exclude_paths = ["vendor"]                 # repeated --exclude-path

[ranking]
enabled = false                            # --ranking; read "The Ranking Algorithm" first
# Four weights; they must sum to 1.0. These are the documented defaults.
weights = { commits = 0.30, lines = 0.25, consistency = 0.25, recency = 0.20 }

[areas]
enabled = false                            # --area-authors
depth = 3                                  # --area-depth
```

---

## Understanding the Report

The sections are in the order the report shows them. **Who Changed Each Area** and **Contributor
Rankings** appear only when asked for. For the order to read them in and what each supports, see
[PLAYBOOK.md](PLAYBOOK.md).

### Header and notice

The repository's name, its remote URL with any credential removed, the analysed branch, the period
and when the report was generated. When they apply, lines state how many contributors are listed,
how many commits are dated after the window, how many could not be read, and that the repository
is a shallow clone. One sentence states the report's limits: the figures are computed from Git
history by fixed rules, offline, and history can be incomplete or wrong, so check before relying
on them for a decision.

### Read Before Using These Figures

A panel under the summary cards states, with this report's own numbers, the rules that most
change a reading: commits are counted, not weighed; how many merge commits were left out; a squash
merge is one commit by one author, with others shown only through Co-authored-by trailers (and
how many commits carry one); dates are commit dates; whether a `.mailmap` merged identities; and
that concentration is not a bus factor. It is in the file because a report is forwarded without
this guide.

### Summary cards

Total Commits, Contributors, Hold(s) Half the Commits, Longest Quiet Run (days) and Distribution
(Gini).

- **Total Commits** counts every non-merge commit in the window, after `--exclude-author`,
  including commits by automated accounts.
- **Contributors**, **Hold Half the Commits** and the **Gini** count people. An identity whose
  name or address carries `[bot]` is an automated account: it is counted in the commit and line
  totals, and listed in the table if it meets `--min-commits`, but not in these three figures, and
  a line under the cards says how many accounts and commits that left out. An automated account
  without the suffix is counted as a person; `--exclude-author` or a `.mailmap` deals with it
  ([ADR 0017](adr/0017-distribution-figures-count-people.md)).
- **Hold Half the Commits** is the fewest people whose commits together make at least half of the
  people's commits. A value of 1 means one person made most of them.
- **Longest Quiet Run** is the longest run of calendar days with no commit between two days that
  had one. The silence since the last commit is stated by a finding instead.
- `--min-commits` changes none of these.

Hold Half the Commits is not a bus factor. Bus factor asks how much of the code still in the
repository only one person understands, which needs `git blame` across every file, not commit
counts. Treat a low value as a prompt to look at who owns which files, not as a measurement of that
risk.

### What the History Shows

A few sentences generated from the report's figures by fixed rules, without a language model: the
same history always gives the same sentences. They name nobody. With fewer than three people, a
sentence that would in effect describe one identifiable person, such as a share of commits or a
weekend-working pattern, is left out.

### Contribution Distribution

A Lorenz curve of how evenly commits are spread across the people in the window, with the Gini
coefficient as one number. The dotted diagonal is perfect equality; the further the solid line
bows beneath it, the more concentrated the commits. Read it as a description, not a score.

- One person has a Gini of 0 by definition, and the curve is not drawn.
- One maintainer with many occasional contributors scores high for ordinary reasons.
- The maximum for *n* people is `(n-1)/n`, never 1.0, so the value is comparable against this
  repository over time, not against another. The caption states the maximum.

### Commit Activity Heatmap

Commits per calendar day, one row per weekday and one column per week, over the weeks of the
window only. Days outside the window have no cell rather than being drawn as days without commits.
Year buttons switch between the calendar years the window covers, and a selector switches between
the whole repository and any one listed contributor. It needs JavaScript.

### Weekly Commit Timeline

Commits per calendar week across the window. Weeks with no commits are drawn as zero. It needs
JavaScript.

### Repository Profile

Six shares of the window, each from 0% to 100%, drawn as separate petals and listed in a table
beside them on a wide screen, below on a narrow one. It is plain HTML and SVG, so it renders
without JavaScript and prints.

| Measure | The share of |
|---|---|
| Continuity | weeks in the window with at least one commit |
| Recent work | commits in the final quarter of the window |
| Shared | people's commits not made by the busiest person; automated accounts are left out |
| Collaboration | commits that credit a co-author |
| Revisiting | files touched by more than one commit; lock files are left out |
| Automation | commits by automated accounts |

**Expected by chance** is what evenly spread activity would give, computed from each measure's own
arithmetic where that is possible. It is not a target. Collaboration, Revisiting and Automation
have no such value and show a dash, as does Shared when there are no people. None of the six
describes a person ([ADR 0016](adr/0016-the-profile-shape-returns-as-a-flower.md)).

### Change Size per Commit

How many commits changed how many lines (added plus deleted), in buckets that double in width:
0–9, 10–49, 50–199, 200–999, 1,000–4,999 and 5,000 or more. The tallest bar is therefore not the
median; the median is marked. It needs JavaScript.

### Where Change Concentrates

The twelve paths with the most lines changed (added plus deleted) in the window, across everyone.
A file that changes often is one to look at, not one that is wrong. Lock files are left out, and
the caption says how many and how many lines. It needs JavaScript.

### Change by File Type

Lines changed per file extension: the eight largest, then the rest pooled as "other". Files
without an extension, including dotfiles, are one entry; so are lock files. It needs JavaScript.

### Per-Contributor Commit Frequency

Commits per week for up to four listed contributors, in table order, told apart by colour and by
dash pattern. It is not drawn with fewer than two. It needs JavaScript.

### Who Changed Each Area

Only with `--area-authors`. The eight most-changed directories (by commits), up to `--area-depth`
levels deep: how many commits changed each, how many authors made them, when it was last changed,
and the authors' names alphabetically. No count or date is given per person. When an area has more
than five authors, the five shown changed it most recently, still alphabetical, and the line says
so. Automated accounts are listed apart; an author below `--min-commits` is counted but not named;
an excluded author is neither. It says who changed an area, not who knows or owns it.

### Contributors

One row per listed contributor: name and email address, commits, lines added, lines deleted, net
lines, active days and the date of the last commit. Lines count every file in each commit,
generated files included, so they are a volume signal, not a quality signal. Net lines is added
minus deleted; a large negative value is usually someone removing code. Active days is the number
of distinct dates with at least one commit. A long table scrolls inside its panel and prints in
full. Identities credited only by a `Co-authored-by` trailer are named beneath it; a trailer is
not verified.

With `--ranking` this section is headed **Contributor Rankings** and adds a rank, a tier and a
composite score.

### Contribution Breakdown

A donut of each contributor's share of all commits, and a bar chart of lines added and deleted per
listed contributor. Contributors beyond four, and anyone `--min-commits` keeps out of the table,
are pooled into one "Other Contributors" slice, so the slices add up to every commit. It needs
JavaScript.

### Without JavaScript

The header, cards, written findings, Repository Profile and contributor table are plain HTML. The
other eight sections, which hold nine charts, need JavaScript. Each carries its figures in a table
for screen readers, which is not shown on screen, so with JavaScript off a sighted reader sees an
empty panel.

---

## What the Report Contains About People

For each listed contributor, the HTML, JSON and CSV carry:

- the name and email address recorded in the commits;
- commits, lines added, lines deleted, net lines and active days;
- the date of the last commit (and, in JSON, of the first);
- how many commits credit the identity as a co-author;
- in JSON and CSV, a `rank` in table order (by commits); with `--ranking`, the rank follows the
  score, and the report adds a tier, a designation, a score and (in JSON) a percentile.

The HTML also carries, for each listed contributor, commits per day (the heatmap selector) and up
to four contributors' commits per week, and file paths with their line counts (Where Change
Concentrates). With `--area-authors`, the HTML names the authors of each of the eight
most-changed directories, and the JSON lists those directories with their authors' names and
addresses and the date each was last changed.

The HTML and JSON carry the repository's name, the analysed branch and its remote URL, and name the identities credited only by a `Co-authored-by` trailer; the JSON
gives their addresses and the hash of the analysed commit. The CSV is the contributor table
alone, with no file paths. The JSON carries directory paths only with `--area-authors`.

The remote URL loses any password, query string and fragment. An SSH login name and the path stay
unless you pass `--hide-emails`, and a token written into the path is not recognised as one.

`--exclude-author` values are recorded only as a count. `--exclude-path` values are recorded as
written, in the report header and in `provenance.filters.exclude_paths`, so a path that names a
client or a person names them in the report, with or without `--hide-emails`. `reveille summary` names nobody (with one or two people, its counts can identify someone).
`reveille who-changed` names the authors of one path; its JSON adds their addresses.

Every HTML report also ends with the licence notices of the chart library it embeds. They name
that library's authors, some with an email address, and are the same in every report; the
option `--hide-emails` leaves them as they are.

Reveille sends none of this anywhere. The file goes where you write it, and anyone who receives it
receives all of the above. Given to a hosted AI assistant, the JSON goes to that assistant's
provider.

## Before You Share a Report

1. **Decide who needs it**, and send it only to them. The HTML is self-contained, so the recipient
   needs only a browser. Whether a mail system accepts a 1.7 MB attachment has not been measured;
   if one refuses it, compress the file or use a file store.
2. **Remove anyone who should not appear** with `--exclude-author`. `--min-commits` is **not** a
   privacy control: it hides rows, while their commits stay in every figure and can be worked out
   from them.
3. **Leave the addresses out** with `--hide-emails` when the recipient does not need them. Names
   stay, so it reduces what the report gives away; it does not make anyone anonymous. With or without
   it, the report is personal data about the people it names.
4. **Leave `--ranking` and `--area-authors` off** unless the question needs them.
5. **For an assistant or a script, prefer `reveille summary`**, which names no contributor, or
   bound the JSON with `--limit`.
6. **Naming nobody does not hide anyone.** With few people, a figure traces to one person; the
   repository name, branch, remote URL (an SSH login, an address, or a local remote's
   directories included, unless `--hide-emails`), title and file paths can identify someone too. A report already sent is not changed by a later `--exclude-author`.
7. **Whether you may use a report about the people who work with you** is a question for the law
   and the agreements that apply to you. [COMPLIANCE.md](COMPLIANCE.md) sets out who is
   responsible for what. This guide is not legal advice.

To share a report from a shared machine or a web directory, change its permissions first (see
[Output path](#output-path)).

---

## The Ranking Algorithm

Each listed contributor gets a composite score from four metrics, each in [0, 1]:

- **Commit volume**: commits in the window, min-max normalised across contributors.
- **Lines contributed**: lines added plus deleted, normalised the same way. It counts lines of any
  kind, generated files included, so it says how much text changed, not how much the change
  mattered.
- **Activity consistency**: active days divided by calendar days in the window (60 of 90 days is
  0.667). Not further normalised.
- **Recency**: commits binned by ISO week, the week containing the end of the window weighted 1.0
  and each earlier week multiplied by 0.85 per week of distance; the score is the sum of commits
  times week weight.

The composite is the weighted sum: commits 30%, lines 25%, consistency 25%, recency 20%. These
weights are a documented judgement, not a derived model: no study establishes that these four
signals in this proportion measure anything in particular. Commit volume is highest because it is
the least distorted by file type, generated code, or how a change is split. Lines are lower
because a vendored dependency, a lockfile or a reformatting pass can dwarf months of considered
work. Recency is lowest because it is a property of the window rather than the person: weight it
higher and a contributor's tier swings on the choice of end date. The weights are configurable
because they are a judgement. They must sum to 1.0, and Reveille exits with an error at startup if
they do not.

The composite is converted to a percentile within the listed contributors, and the percentile
sets the tier:

| Tier | Designation | Percentile |
|---|---|---|
| I | Private | 20th or below |
| II | Corporal | above 20th, up to 40th |
| III | Sergeant | above 40th, up to 60th |
| IV | Lieutenant | above 60th, up to 75th |
| V | Captain | above 75th, up to 88th |
| VI | Major | above 88th, up to 95th |
| VII | Commander | above 95th |

Tiers are not absolute: a Captain in a ten-person team may be a Sergeant among thirty, or over a
longer window. Tied scores get identical percentiles and tiers (a tied group sits at the bottom of
its band). A single contributor is Commander by definition, at percentile 100.0.

### What the ranking does not measure

The ranking measures the volume and regularity of commits, because that is what Git records. It
does not measure contribution, productivity, or value, and it should not be used to assess an
individual.

The SPACE framework (Forsgren et
al., 2021) holds that "developer productivity is about more than an individual's activity levels".
DORA's metrics are defined for applications and services, not people. Activity metrics are easy to
game and systematically misread review-heavy, mentoring, part-time and on-call work as low
output. A contributor who spends a quarter unblocking colleagues and deleting a subsystem will
rank below one who committed generated files.

Read a tier as a description of the shape of participation in one window. It is not a statement
about a person. The military designations are labels on a score of commit volume and regularity,
not an evaluation of anyone.

---

## Practical Patterns

**Filtering bot authors.** Bots inflate commit counts and active days. Set the exclusions once:

```toml
[filters]
exclude_authors = ["dependabot[bot]", "renovate[bot]", "github-actions[bot]", "semantic-release-bot"]
```

**Scoping to a release.** Restrict to the branch and dates of the cycle:

```bash
reveille generate --branch release/3.0 --since 2024-09-01 --until 2024-11-30 \
  --title "Release 3.0 — Engineering Retrospective"
```

**Changing the weights.** A maintenance quarter might favour consistency and recency over volume.
This changes the score; it does not make it a measure of contribution.

```toml
[ranking]
weights = { commits = 0.15, lines = 0.15, consistency = 0.40, recency = 0.30 }
```

**Exporting for other tools.** JSON for dashboards and scripts, CSV for a spreadsheet; both are
written at the `--output` stem:

```bash
reveille generate --format json --output /tmp/reports/q4.html   # writes /tmp/reports/q4.json
reveille generate --format csv --output /tmp/reports/q4.html    # writes /tmp/reports/q4.csv
```

---

## Troubleshooting and Questions

**Why does Reveille count fewer commits than `git log`?** Merge commits are excluded. Without
`--until` or `--deterministic`, commits dated after today (UTC) are not counted; the header and
stderr say how many. `--exclude-author` removes an author's commits from every figure.

**"No commits found", exit 1.** No non-merge commit falls in the window on the analysed branch.
Check `--since`, `--until` and `--branch`; the branch defaults to the one checked out.

**The report says the repository is a shallow clone.** Only the fetched history was read. `git
fetch --unshallow` fetches the rest.

**Someone who only merged branches is missing.** Merge commits are excluded, so a person whose
only commits are merges does not appear, and a change made only in a merge is not counted.

**The header says some commits were not read.** A commit whose author field holds the characters
Reveille separates records with cannot be read reliably, so it is left out and counted instead of
guessed at. Ordinary histories have none; one that does was most likely written on purpose
([ADR 0019](adr/0019-how-history-is-read.md)).

**"Partial clone", exit 2.** A clone made with `--filter` leaves objects on the server, and
reading them would make Git fetch. Reveille makes no network call and changes no Git data, so it
refuses. Run it on a clone made without `--filter`.

**`git log` shows history the report leaves out, after a `git replace`.** Reveille reads the
objects the commit hashes name and does not follow replace refs or grafts, so the report and its
recorded hash always describe the same history. The header and stderr say when any are present
([ADR 0018](adr/0018-replace-refs-are-not-honoured.md)).

**One person appears twice.** Their commits carry two addresses. A `.mailmap` at the repository
root joins them (see [How Reveille Works](#how-reveille-works)). `reveille init --mailmap` writes a
template beside a new `reveille.toml`; if `reveille.toml` already exists it stops (exit 2), and
`--force` replaces both files.

**Can I run it on a repository someone sent me?** Git obeys a repository's own `.git/config`,
which can name a program for Git to run. Reveille switches off the ones its reads start (signature
checking, fsmonitor, and content filters during `state`), but Git has many settings. `git clone`
does not copy that file; a copied directory or an archive does. Run Reveille on a fresh clone of
anything you do not trust. See [SECURITY.md](../SECURITY.md).

**"sets its working tree to ...", exit 2.** The repository's `.git/config` sets `core.worktree`
to another directory. Reveille would then read and write there, so it refuses. Remove the setting
(`git config --unset core.worktree`) if it is not meant, or run Reveille in that other directory.

**"is not a regular file (a named pipe or a device)", exit 2, or "`git status` did not finish".**
Git would wait for ever on a named pipe, or read a device without end, at one of these:
`.gitattributes`, `.gitignore`, `info/exclude`, a file Git reads first (`.git/config`,
`config.worktree`, `commondir`, `packed-refs`, `shallow`, `objects/info/alternates`, `HEAD`), or
a file an `include.path` or `includeIf` names (every condition taken as true). Such a file over
8 MiB is refused too, except `packed-refs` and `shallow`, which grow with the repository; so is
anything under `refs/` or `objects/` (and the object directories alternates name) that is not a
regular file. Remove it. Anywhere else, Git is stopped
after 300 seconds (or 300 seconds without output while it reads the history) with "Git did not
finish ... and was stopped", exit 2; `git status` in `reveille state` is stopped after 120
seconds. On Windows only the history read is stopped: GitPython cannot stop a command it waits
for there. `reveille summary` reads no line counts, so a `.gitattributes`
pipe does not affect it.
