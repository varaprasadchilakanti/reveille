# Privacy notice for contributors

**Last updated:** 2026-09-02 · **Applies to:** the Reveille repository and its
contributor licence agreement ([CLA.md](CLA.md))

This is a plain notice about the personal data involved in contributing to
Reveille. It is short because there is very little of it.

## Who is responsible

Varaprasad Chilakanti, an individual, based in India. He maintains Reveille
personally; there is no company or organisation behind it.

**Contact for anything on this page:** the address in
[SECURITY.md](SECURITY.md), or open a GitHub issue. Either reaches the same
person. Questions and requests get a substantive answer.

## What is held, and where

Only what you publish yourself:

| Data | Where it lives | How it got there |
|---|---|---|
| The name and email address in your commits | The Git history, and GitHub | You put it there with `git config` |
| Your GitHub username and profile | GitHub | Your GitHub account |
| The text of your pull request, including the ticked CLA box | GitHub | You wrote it |
| Your `Signed-off-by` trailer | The Git history | `git commit --signoff` |

**There is no separate contributor register.** No `signatures.json`, no
spreadsheet, no database, no third-party CLA service, no mailing list. Nothing
is copied out of GitHub into anywhere else. The record of your CLA acceptance
*is* the pull request and your own commits — data that already existed before
this notice applied to it.

## Why

Two purposes, and no others:

1. **Attribution** — so the version history records who wrote what. This is a
   normal and expected part of how software is developed.
2. **Provenance of the licence chain** — so it can be established, later and by
   anyone, that the code in this project was contributed by someone who had the
   right to contribute it and did so on stated terms. This is the entire
   purpose of the CLA, and it only works if the record is durable.

Nothing is used for marketing. Nothing is sold. Nothing is shared with any
third party beyond GitHub and PyPI, which host the project.

## How long

Indefinitely, and this needs saying plainly: **Git history cannot be edited
after the fact in any practical sense.** Once a commit is merged and cloned by
other people, the name and email in it exist in every one of those copies, on
machines that are not under anyone's control. GitHub says the same thing about
its own service: *"You cannot remove sensitive data from other users' clones of
your repository"* and *"If the commit that introduced the sensitive data exists
in any forks, it will continue to be accessible there"*
(<https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository>).

The Developer Certificate of Origin, which you certify when you sign off a
commit, states the same in its clause (d): the record *"is maintained
indefinitely and may be redistributed"*.

**The practical consequence: decide before you commit, not after.** If you do
not want your email address published permanently, configure Git to use a
GitHub no-reply address first — see
<https://docs.github.com/en/account-and-profile/reference/email-addresses-reference>.
A signed-off commit with a no-reply address is accepted here.

## Your rights, and their honest limits

Whichever data protection law applies to you, you can ask for access to what is
held, correction of anything wrong, erasure, or that processing stop. Ask via
the contact above.

Here is the honest position on each:

- **Access.** Straightforward. Everything held is already public and can be
  listed for you.
- **Correction.** For anything outside Git history — a mistake in a document, a
  wrong attribution in a release note — this can be fixed. For a name inside an
  existing commit, a correcting note can be added, and future commits can use
  whatever you prefer.
- **Erasure and objection.** From anywhere other than Git history: yes. **From
  Git history: realistically, no.** Rewriting history changes every subsequent
  commit hash, breaks every existing clone and fork, and does not reach copies
  other people already hold. This is a property of the technology, not a
  refusal. Where retention is necessary to establish or defend the licence
  chain, it is also a purpose for which the record is kept. If you ask, you will
  get a straight explanation of what can and cannot be done in your specific
  case, rather than a form letter.
- **Complaint.** You can complain to a data protection authority in your own
  country if you think this is wrong.

## GitHub's own role

GitHub hosts this repository and has its own privacy statement, which governs
what GitHub does with your data as the operator of the service:
<https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement>.
Your relationship with GitHub is your own, through your own account.

Note also GitHub's terms: *"By choosing to contribute Content to a public
repository, you are choosing to and directing us to make such Content
accessible to everyone on the internet."*
(<https://docs.github.com/en/site-policy/github-terms/github-terms-of-service>)

## Changes

If this notice changes, the new version replaces this one at this path and the
change is visible in the repository's Git history, which is the point.

---

*The maintainer is not a lawyer and this notice is not legal advice. It is an
honest description of what actually happens, written so that a contributor can
make an informed decision before committing.*

---

## Regulatory position

This document covers what data exists and who is responsible for it. The wider
question — which regulations engage at all — is recorded separately in
[docs/COMPLIANCE.md](docs/COMPLIANCE.md), with the provision each conclusion
rests on. In short: the maintainer is neither controller nor processor for the
tool's operation, and the project is outside the Cyber Resilience Act, the
Product Liability Directive, the AI Act, the EU Accessibility Act and the US
export regulations. Neither document is legal advice.
