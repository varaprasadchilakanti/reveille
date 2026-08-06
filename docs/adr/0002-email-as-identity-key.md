# 0002 — Email is the contributor identity key

**Status:** Accepted

## Context

Git has no concept of a user account. A commit carries a free-text name
and email, both set by whoever authored it, neither verified. The same
person routinely appears as several identities: a work address and a
personal one, a laptop with a misconfigured `user.name`, a GitHub
noreply address, a name spelled with and without an accent.

Something has to decide when two commits belong to the same person, and
every available answer is a heuristic.

## Decision

Contributors are keyed on **lowercased email**. Display name comes from
the most recent commit under that key.

Two normalisations run before the key is taken:

1. **`.mailmap`**, all four forms from `gitmailmap(5)`, matched
   most-specific-first (name-and-email, then email-only, then
   name-only), case-insensitively. This is the mechanism Git itself
   provides, and the repository owner is the right authority.
2. **GitHub noreply folding.** The legacy
   `username@users.noreply.github.com` and post-2017
   `12345678+username@users.noreply.github.com` forms both exist and one
   person commonly has both. The numeric prefix is stripped so they
   collapse.

## Consequences

Email is more stable than name — people change employers more often
than they change how they spell their own name, and a name collision
between two people is more likely than an email collision.

But the failure mode is real: **one person with two unmapped addresses
appears as two contributors, and their commits are split across both
rows.** Reveille cannot detect this, because nothing in Git says they
are the same person. The fix is a `.mailmap`, which is why
`reveille init --mailmap` generates an annotated template.

The opposite failure also exists: a shared address, such as a CI bot or
an old `root@localhost`, collapses several actors into one row. The
four-field `.mailmap` form is the remedy, and the template documents it.

Display name from the most recent commit means a rename is picked up
automatically, at the cost of the report not matching what someone
remembers from older history.
