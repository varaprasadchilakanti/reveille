# 0018 — Reveille reads the objects its hashes name; replace refs are not honoured

**Status:** Accepted (2026-10-09)

## Context

`git replace` lets a repository substitute one object for another: every Git command that reads
the original then sees the replacement, unless told not to. Replace refs live under
`refs/replace/`, are not fetched by default, and travel with a copied directory or an archive.

Reveille honoured them silently. Measured on 2026-10-09: a one-commit repository whose commit
`863dcb0` was authored by "A", with a replace ref substituting a copy authored by "Mallory".
The report listed one contributor, Mallory, while `provenance.head_sha` recorded `863dcb0` — a
commit Mallory did not author. A reader who checked the hash against the history would find a
different author from the one the report names.

The JSON's `provenance` exists so that two reports can be reconciled and a figure re-performed
(ADR 0008), and the audit reader the project now writes for needs exactly that. A report that
names one set of objects and describes another defeats it.

## Decision

- **Every Git command Reveille runs sets `GIT_NO_REPLACE_OBJECTS=1`, and points
  `GIT_GRAFT_FILE` at an empty file.** The history read is the one the recorded hashes name,
  whatever `refs/replace/` or the deprecated `.git/info/grafts` holds; the first setting does not
  cover the second, which a verification pass found still obeyed.
- **Grafts, whether made with `git replace --graft` or written to `.git/info/grafts`, are
  therefore not followed either.** A repository
  that joins an older history on with a graft is read without it, so its figures start where its
  own history starts. The User Guide says so.

## Consequences

- `provenance.head_sha` and the figures describe the same objects. `git log` run with
  `--no-replace-objects` and `GIT_GRAFT_FILE=/dev/null` reproduces the commit set; without the
  second, a `.git/info/grafts` file still applies.
- A user who relies on a graft sees fewer commits than `git log` shows them. The remedy, if they
  want the older history counted, is to make it real history (`git filter-repo` or a merge),
  which is a change to their repository and therefore theirs to make.
- Recording which replace refs were present, in `provenance`, is left for a later release; it
  would be an addition to the schema.
