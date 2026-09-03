# 0009 — A contributor licence agreement is required for pull requests

**Status:** Accepted

## Context

[0007](0007-apache-2-0-licence.md) recorded Apache-2.0 §5 — inbound equals
outbound — as a reason to move licence *now*, and stated the benefit as "a pull
request is automatically licensed under the project's terms, with no
contributor licence agreement to administer." That statement remains true as
far as it goes. This record narrows it.

§5 licenses a contribution under *this* licence and no other:

> Unless You explicitly state otherwise, any Contribution intentionally
> submitted for inclusion in the Work by You to the Licensor shall be under the
> terms and conditions of this License, without any additional terms or
> conditions.

That is sufficient for distributing Reveille as it is. It is not sufficient for
changing what Reveille is distributed as. If the project ever needed a
different outbound licence — a future Apache version, a second licence
alongside it, a dual-licensing arrangement — §5 alone would require the
agreement of every past contributor, individually, one at a time, forever. The
same sentence in §5 anticipates the fix:

> Notwithstanding the above, nothing herein shall supersede or modify the terms
> of any separate license agreement you may have executed with Licensor
> regarding such Contributions.

The window to act is now, for the same reason 0007 gave: the agreement reaches
only contributions received after it is adopted. `src/` currently has exactly
one human author, so adopting it today costs nothing retroactively and covers
everything that follows. Every month of delay is a contribution it cannot
cover.

The Linux Foundation lists "a desire for the project to have the ability to
change to a different open source license in the future" as one of three
standard reasons projects adopt a CLA
(<https://bestpractices.linuxfoundation.org/ip/contribution-mechanisms-cla.html>).
That is the reason here. It is the only reason here — there is no company, no
foundation, and no dual-licensing plan today.

The cost is real and is not being talked down. A CLA is friction; the Linux
Foundation names "increased friction and slower onboarding of new contributors"
in the same paragraph. Some competent contributors decline to sign CLAs on
principle. For a project with zero external contributors to `src/`, the friction
is currently theoretical and the optionality is permanent — but the ratio
reverses the moment the project attracts a community, and this record should be
revisited if it does.

## Decision

**Pull requests require acceptance of `CLA.md`, version 1.0. Issues and
discussion require nothing.**

Four things follow from that, each chosen deliberately.

**The agreement is a licence, not an assignment.** Contributors keep their
copyright. §2.1 says so, and the grant is non-exclusive. An assignment would
buy no additional optionality that a sublicensable licence does not already
buy, and would cost far more goodwill.

**The relicensing right has a floor.** §2.3(b) obliges the maintainer to keep
licensing every contribution under the licence in force on that contribution's
submission date, whatever else is added on top. This is Harmony Option Five,
adapted. The unbounded version of that clause — relicense freely, no floor — is
what makes CLAs unpopular, and it buys nothing this project needs. A licence
that can be *added to* but not *taken away* preserves the optionality without
the reputational cost.

**Acceptance is recorded in data the contributor already published, and nowhere
else.** A ticked box in the pull request body, plus a `Signed-off-by` trailer on
each commit. No `signatures.json`, no database, no third-party CLA service. The
`cla` workflow verifies both and writes nothing. This is a data-protection
decision as much as an ergonomics one: a committed register of names and email
addresses, ordered so that individuals are retrievable, is a filing system the
maintainer controls, with all the obligations that follow. Commit metadata the
contributor authored and published is not something the maintainer collected.

**DCO and CLA are both required, and they do different jobs.** The DCO is a
certification of provenance by the author — "I wrote this and may submit it".
The Linux Foundation is explicit that it "is not itself a license. It does not
contain a grant of license rights"
(<https://bestpractices.linuxfoundation.org/ip/contribution-mechanisms-dco.html>).
The CLA is the grant. Here the sign-off does double duty: it carries the DCO
certification, and it supplies the identifying act that makes the checkbox
attributable to a person. Neither substitutes for the other.

Two jurisdiction-specific points shaped the drafting and are recorded here so
they are not undone by a later tidy-up.

**Indian statutory defaults would otherwise gut the grant.** Section 30 of the
Copyright Act, 1957 lets an owner grant an interest "by licence in writing" —
note that, unlike section 19(1) for an assignment, section 30 does not say
"signed", which is why this is a licence and not an assignment and why a
checkbox suffices. But section 30A applies section 19 to licences, and section
19 supplies hostile defaults where particulars are missing: an unstated period
becomes five years (19(5)), an unspecified territory becomes India alone
(19(6)), and rights not exercised within a year lapse "unless otherwise
specified" (19(4)). §2.8 of `CLA.md` states all three expressly. **Do not delete
§2.8 as boilerplate — without it the relicensing right this whole record exists
to secure would expire in five years, apply only in India, and lapse if unused
for twelve months.**

**Consideration has to be real.** An agreement without consideration is void
under section 25 of the Indian Contract Act, 1872, and none of that section's
three exceptions could apply to a contribution from a stranger. Section 2(d)
accepts a promise as consideration, but a CLA that says the maintainer owes
nothing offers no promise at all. §6.3 therefore contains three binding
promises given at the contributor's request, and §2.3(b) is a real continuing
obligation. §2.6 (no obligation to *merge*) is compatible with §6.3(b) (a
promise to *consider and respond*), and the distinction is deliberate.

## Consequences

**What this costs.**

- Every pull request now has a step that can be forgotten, and a CI job that
  will fail when it is. First-time contributors will hit it.
- Some contributors will not accept a CLA at all. That is a permanent, unmeasured
  loss, and it will not announce itself — people simply do not open the pull
  request.
- The maintainer becomes the counterparty to a contract, personally. The
  agreement names an individual, because a project is not a legal person capable
  of entering agreements.
- `CLA.md` is a document adapted from other people's texts without legal review.
  It says so, in it.

**What this rules out.**

- Silently dropping the requirement later. It can be dropped — a maintainer can
  always stop asking for rights — but every contribution accepted while it was
  in force stays governed by it, and the version history has to remain readable
  to show which text applied when.
- Using the popular CLA-bot workflow. `contributor-assistant/github-action`
  commits a signatures file to a repository by default and its README does not
  mention personal data at all. That is precisely the shape this record rejects.

**What is now owed on the data-protection side.**

- `PRIVACY.md` exists and has to stay accurate. A solo maintainer in India is
  prima facie within the DPDP Act 2023 via s.3(a), which — unlike GDPR Art. 3 —
  contains no requirement that the data subject be in India. The best arguments
  against exposure are s.3(c)(ii) (data the contributor herself made public),
  s.7(a) (voluntarily provided), and s.17(1)(a) (necessary for enforcing a legal
  right or claim). All three are strongest when the only data held is data the
  contributor published. That is a second, independent reason for the no-register
  design.
- The comfortable assumption that a small operation is exempt from the GDPR's
  record-keeping and EU-representative duties does not survive contact with the
  word "occasional". Both Art. 30(5) and Art. 27(2)(a) turn on it, and
  collecting an acceptance on every contribution is not occasional. The thing
  that keeps those duties away is therefore not smallness — it is not falling
  under Art. 3(2) in the first place, which in turn means not accumulating the
  recital 23 targeting signals (EU-currency pricing, named EU markets, EU
  adopter lists). Worth knowing before the marketing copy is written.
- Whether the GDPR applies at all is genuinely arguable and was not resolved.
  The household exemption is not available — a public repository is not a purely
  personal or household activity — so everything rests on Art. 3.

**What has to be maintained.**

- `CLA.md` is versioned, immutably. Superseded versions move to `docs/cla/` and
  stay there. Changing the text never changes the terms of a contribution
  already made.
- The `cla` workflow's `CLA_VERSION` must be bumped in the same commit as any
  new version of the document, and the pull request template line updated to
  match, or every open pull request fails.

**Supersedes nothing.** [0007](0007-apache-2-0-licence.md) stands; this record
qualifies its third bullet, which should be read alongside this one.
