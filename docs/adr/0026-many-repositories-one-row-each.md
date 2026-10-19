# 0026 — Many repositories, one row each: `reveille repos`

**Status:** Proposed (2026-10-17).

## Context

People who look after many repositories ask which of them are still worked on. Bitbucket Cloud
closed the request for a workspace dashboard of that kind as Won't Fix (BCLOUD-21696, 2022), its
contributor-statistics request (BCLOUD-4307, 565 votes) was closed without a stated feature, and
Atlassian's own guidance for Data Center (2025) is to run `git log` on a clone. Comparable tools
have been asked for the same for years (gitinspector #24, opened in 2014; git-of-theseus #4;
git-fame #29). Today the answer takes one Reveille run per repository and a spreadsheet.

The project holds that it builds no cross-repository view of a person: a per-person table across
repositories is the shape of a monitoring tool, whatever it is called.

## Decision

**A new command, `reveille repos <directory>`, that finds the Git repositories in a directory and
gives one row per repository, about the repository, never about a person.**

- **What a row says:** the path relative to the directory, the checked-out branch, the date of the
  last non-merge commit and the days since it, the commits in a recent window, the people and the
  automated accounts in that window as **counts**, whether it is a shallow clone, and a status.
- **Status, by fixed rules over the days since the last commit:** *active* within the window
  (default 90 days, `--days`), *quiet* within 365 days, *dormant* beyond that, *empty* with no
  commit. The rules are stated in every output.
- **What it never says:** no name or address of anyone, no person counted or followed across
  repositories, no total of people across repositories (one person in three repositories would be
  counted three times, and a deduplicated total would need exactly the cross-repository identity
  this record refuses).
- **Each repository is read as `summary` reads one:** the same reader, its refusals and pins,
  `.mailmap` and `--exclude-author`, no line counts. A repository that cannot be read (a partial
  clone, a SHA-256 repository, a corrupt one) gets a row saying why, and the others are still
  read. An exclusion value that matches nothing in **any** repository is reported once.
- **Finding repositories:** a working tree (a directory holding `.git`) or a bare repository
  (`HEAD`, `objects` and `refs`), to a depth of 1 by default and at most 3 (`--depth`). A
  repository found is not searched further, so submodules and nested clones are not rows. A
  symbolic link is not followed, so the search stays inside the directory given.
- **Formats:** text, JSON, Markdown and CSV. There is no HTML page: the answer is a table.

## Consequences

- The question "which of these are still worked on" takes one call, offline, over a folder of
  clones or of server-side mirrors.
- A row's people count describes one repository. Adding the column up says nothing about how many
  people there are.
- A repository's own refusal does not stop the run, so the exit code no longer means "every input
  was read": the rows say which were not, and the totals count them.
- The status rules are a judgement, not a measurement of health. A finished library is dormant and
  fine; an active repository may be one bot.
- Reading every repository costs one history read each, without line counts. On a directory of
  thousands this is minutes, not seconds; `--depth` bounds the search.
