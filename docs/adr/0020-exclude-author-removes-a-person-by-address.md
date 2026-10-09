# 0020 — `--exclude-author` removes a person by every address the value reaches

**Status:** Proposed. Extends ADR 0002.

## Context

`--exclude-author` is the one option whose purpose is privacy: someone asks not to appear. ADR
0002 makes an identity its address. Exclusion was matched per commit against the name or address
on that commit, so one person committing as "Ana" and "Ana Silva" from one address, excluded as
"Ana Silva", stayed in the report as "Ana" — exit 0, no warning (found 2026-10-09).

Matching per address instead raises the opposite risk. A name is not unique: with two people
called Alice at different addresses, excluding "Alice" reaches both (reproduced in the 2026-10-09
ADR review).

Three ways were weighed:

- **Per commit.** Rejected: it leaves a person in the report under any other name, the failure
  the option exists to prevent.
- **Per address, refusing a name that reaches more than one.** Rejected: it fails closed on the
  common case of one person with several addresses joined by a `.mailmap`, and makes the user
  re-run.
- **Per address, stating when a name reached more than one.** Chosen.

## Decision

- An exclusion value is matched, case-insensitively, against each commit's name and address as
  recorded and as resolved through `.mailmap`. **Every commit made under an address that a value
  matched is removed**, whatever name it carries, and so is every address a `.mailmap` ties to it.
- **When a value reaches more than one address**, a warning on stderr names the addresses and says
  that an address excludes only one.
- A value that matches nothing is still warned about.

## Consequences

- Excluding a person removes them, which is the direction a privacy option should err in.
- Two people who share a name are both removed when excluded by that name, and the user is told,
  with the addresses to narrow it.
- Two people who share an address were already one identity (ADR 0002); excluding either removes
  both, as before.
- The addresses a value reaches are found across every commit reachable from the analysed
  revision, not only the window or the path being read: a name used before `--since`, or only
  in other files, still removes that address. This costs one more `git log` reading names and
  addresses, only when something is excluded.
