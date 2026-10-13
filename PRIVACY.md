# Privacy notice for contributors

**Last updated:** 2026-10-13 · **Applies to:** the Reveille repository and its
contributor licence agreement ([CLA.md](CLA.md))

This notice covers the personal data involved in contributing to Reveille. It is for
contributors; what the tool's report contains about people is in the
[User Guide](docs/USER_GUIDE.md#what-the-report-contains-about-people).

## Who is responsible

Vara Prasad Chilakanti, an individual, based in India. He maintains Reveille
personally; there is no company or organisation behind it.

**Contact:** open a [GitHub issue](https://github.com/varaprasadchilakanti/reveille/issues) for
anything you are content to discuss in public, or use
[GitHub's private reporting form](https://github.com/varaprasadchilakanti/reveille/security/advisories/new)
if you are not; it reaches the same person privately, and you do not have to be reporting a
vulnerability to use it. No email address is published for privacy requests; the conduct contact
is in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## What is held, and where

Only what you publish yourself:

| Data | Where it lives | How it got there |
|---|---|---|
| The name and email address in your commits | The Git history, and GitHub | You put it there with `git config` |
| Your GitHub username and profile | GitHub | Your GitHub account |
| The text of your pull request, including the ticked CLA box | GitHub | You wrote it |
| Your `Signed-off-by` trailer | The Git history | `git commit --signoff` |

There is no separate contributor register: no `signatures.json`, spreadsheet, database,
third-party CLA service or mailing list, and nothing is copied out of GitHub. The record of your
CLA acceptance is the pull request and your own commits.

## Why

Two purposes, and no others:

1. **Attribution**: the version history records who wrote what.
2. **Provenance of the licence chain**: so anyone can establish later that code was contributed by
   someone with the right to contribute it, on stated terms. This is the purpose of the CLA, and
   it only works if the record is durable.

Nothing is used for marketing or sold, and nothing is shared beyond GitHub and PyPI, which host
the project.

## How long

Indefinitely. Git history cannot be edited after the fact in any practical sense. Once a commit
is merged and cloned, the name and email in it exist in every copy, on machines nobody controls.
GitHub says the same about its own service: *"You cannot remove sensitive data from other users' clones of
your repository"* and *"If the commit that introduced the sensitive data exists
in any forks, it will continue to be accessible there"*
(<https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository>).

The Developer Certificate of Origin, which you certify when you sign off, says so in clause (d):
the record *"is maintained indefinitely and may be redistributed"*.

Decide before you commit, not after. If you do
not want your email address published permanently, configure Git to use a
GitHub no-reply address first; see
<https://docs.github.com/en/account-and-profile/reference/email-addresses-reference>.
A signed-off commit with a no-reply address is accepted here.

## Your rights, and their limits

Whichever data protection law applies to you, you can ask for access, correction, erasure, or that
processing stop. Ask via the contact above. The position on each:

- Access: everything held is already public.
- Correction: for anything outside Git history, such as a mistake in a document or a
  wrong attribution in a release note, this can be fixed. For a name inside an
  existing commit, a correcting note can be added, and future commits can use
  whatever you prefer.
- Erasure and objection: from anywhere other than Git history, yes. From
  Git history, realistically no. Rewriting history changes every subsequent
  commit hash, breaks every existing clone and fork, and does not reach copies
  other people already hold. That is a property of Git, not a
  refusal. Where retention is necessary to establish or defend the licence chain, that is also a
  purpose for which the record is kept. If you ask, you get an explanation of what can and
  cannot be done in your case.
- Complaint: you can complain to a data protection authority in your own
  country if you think this is wrong.

## GitHub's own role

GitHub hosts this repository, and its own
[privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)
governs what it does with your data. Your relationship with GitHub is your own. Its terms say: *"By choosing to contribute Content to a public
repository, you are choosing to and directing us to make such Content
accessible to everyone on the internet."*
(<https://docs.github.com/en/site-policy/github-terms/github-terms-of-service>)

## Changes

A changed notice replaces this one at this path, and the change is visible in the repository's
Git history.

---

*The maintainer is not a lawyer; neither this notice nor COMPLIANCE.md is legal advice.*

## Regulatory position

Which regulations engage at all is recorded in [docs/COMPLIANCE.md](docs/COMPLIANCE.md), with the
provision each conclusion rests on. In short, on the maintainer's reading: the maintainer is
neither controller nor processor for the tool's operation, and the project is outside the Cyber
Resilience Act, the Product Liability Directive, the EU Accessibility Act and the US export
regulations, and is not an AI system under the AI Act. The Cyber Resilience Act and Product
Liability Directive conclusions turn on the software being supplied outside the course of a
commercial activity.
