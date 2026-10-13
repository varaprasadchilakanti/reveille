# 0023 — GitHub noreply addresses fold on the account number

**Status:** Proposed (2026-10-12). Partly supersedes ADR 0002 (its second normalisation).

## Context

ADR 0002 folds GitHub's two noreply forms, legacy `username@users.noreply.github.com` and
`12345678+username@users.noreply.github.com`, by stripping the number, so the username is the key.
GitHub lets a user change their username, and a released username can be taken by another
account; the number never changes and is never reused. Keyed on the username, both failures can be reproduced: one account renamed from `alice` to `alice2` became two
people, and two accounts that each used `alice` became one. Merging two people is the worse of
the two: one person's commits are shown, counted and excluded under another's name.

## Decision

- **A prefixed address folds on its account number**, to `<number>+<current username>@...`, the
  username most recently seen for that number on the analysed branch.
- **A legacy address joins an account only when exactly one account in the branch's history used
  its username.** Otherwise it stays as it is: a separate identity.
- The account table comes from one read of author addresses on the branch, newest first, and is
  carried with the `.mailmap` tables so every identity lookup applies the same rule. A `.mailmap`
  entry still wins, matched on the raw address, the account's address, or the legacy form.

## Consequences

- Reports show noreply identities with their number, which is what Git records; scripts that
  joined on the stripped form must join on the new form.
- A legacy-only identity whose username two accounts used stays split from both. That
  under-merges, which a `.mailmap` line fixes; the old rule over-merged, which nothing could undo
  without editing history.
- An address seen only in a `Co-authored-by` trailer keeps its number: the table reads authors.
- One more `git log` of author addresses per run; on a 9,000-commit history it costs a fraction
  of a second.
