# Regulatory position

**This is a record of research, not legal advice, and it was not written by a
lawyer.** It exists so that the reasoning is visible and can be argued with,
rather than left implicit. Every conclusion below is stated with the provision it
rests on, so a reader who disagrees knows exactly where to push.

The short version: **Reveille is out of scope for every regime examined**, and
the single thing that would change that is taking money for it.

---

## What the software actually does

Every conclusion here depends on these facts, so they are stated first:

- It runs **entirely on the user's own machine**. No network call at runtime, no
  telemetry, no server, no account. The maintainer never receives anything.
- It reads Git commit metadata — object name, author name, author email,
  timestamp — and writes one report. It reads **no source code**, no commit
  messages, no diffs.
- It contains **no machine learning and no model**. Every number it produces is
  deterministic arithmetic over commit counts.
- It is supplied **free of charge and outside any commercial activity**. There is
  no paid tier, no hosted version, no paid support, and no donation scheme.

## GDPR — Regulation (EU) 2016/679

Commit author names and email addresses are personal data under Art. 4(1), and
reading them is processing under Art. 4(2). So the question is not whether
personal data is involved; it is **who is responsible for it**.

A controller is whoever "determines the purposes and means of the processing"
(Art. 4(7)). The maintainer determines neither: the user chooses a repository,
runs the command, and decides what to do with the report. A processor "processes
personal data on behalf of the controller" (Art. 4(8)); the maintainer processes
nothing, because no data ever reaches them.

**The maintainer is therefore neither controller nor processor for the tool's
operation. The user is the controller.** Where that user is an organisation
analysing its own repositories, this is ordinary employment-context processing
and their existing basis covers it.

Recital 78 addresses software producers only in hortatory terms — they "should be
encouraged" to consider data protection in design — while Art. 25's binding
obligations fall on the controller.

**What this means for you, as a user:** the generated report contains contributor
names and email addresses. If you circulate it, you are handling personal data
and that is your responsibility, not the tool's. `--exclude-author` removes a
person entirely, matching both their pre- and post-`.mailmap` identity, and tells
you if it matched nothing.

## EU Cyber Resilience Act — Regulation (EU) 2024/2847

**Out of scope**, on the commercial-activity gate rather than on any technical
argument.

Art. 3(22) defines "making available on the market" as supply "in the course of a
commercial activity, whether in return for payment or free of charge". Being free
is not the exemption; being non-commercial is.

Recital 18 is explicit that free and open-source software not monetised by its
maintainer is not supplied in the course of a commercial activity, that how the
software was developed or financed is irrelevant to that question, and that
regular releases do not by themselves imply commerce. Recital 20 adds that
**hosting on a package manager is not, by itself, placing on the market** — so
publishing to PyPI does not change the position.

The Act's lighter "open-source software steward" regime (Art. 3(14)) does not
apply either, and cannot: a steward must be a **legal person**, which excludes an
individual maintainer.

**Timeline:** Art. 14 reporting obligations apply from 11 September 2026;
Chapter IV from 11 June 2026; full application 11 December 2027.

## Product Liability Directive — Directive (EU) 2024/2853

**Out of scope, through the same gate** — and this is the one worth
understanding, because it is strict liability, against which a warranty
disclaimer is no defence.

Art. 2(2): the Directive does not apply to free and open-source software
developed or supplied outside the course of a commercial activity. Recital 14
confirms that providing such software on open repositories is not making it
available on the market unless that occurs commercially.

It applies to products placed on the market **after 9 December 2026**.

> **The cliff-edge worth internalising.** The CRA and the Product Liability
> Directive share the same "outside the course of a commercial activity" test.
> Staying non-commercial keeps this project outside **both**. Introducing a paid
> tier, a hosted version, paid support beyond cost recovery, or donations
> exceeding development costs crosses both lines **at once** — and the liability
> side is strict. Modest sponsorship without profit intent is expressly fine
> (CRA recital 15). "Should I take money for this?" is a materially bigger
> question after 9 December 2026 than before it.

## EU AI Act — Regulation (EU) 2024/1689

**Not an AI system**, so the Regulation does not engage.

Art. 3(1) turns on a system that "infers, from the input it receives, how to
generate outputs". Recital 12 draws the line explicitly: the definition "should
not cover systems that are based on the rules defined solely by natural persons
to automatically execute operations", and the capacity to infer must "transcend
basic data processing".

Counting commits and applying human-authored thresholds is exactly rules defined
by natural persons. There is no model, no learning, no adaptiveness.

**The honest residual, which is reputational rather than legal.** If it *were* an
AI system, Annex III point 4(b) — systems used "to monitor and evaluate the
performance and behaviour of persons" in work relationships — would be an
uncomfortably good fit for a contributor ranking deployed by an employer. And
Art. 2(12) expressly **disapplies** the open-source exemption for high-risk
systems, so "it's Apache-2.0" would not have been a defence.

That is a large part of why the ranking is **off by default** from v0.8.0, and
why the default report measures distribution rather than people. See
[ADR 0010](adr/0010-ranking-is-opt-in.md).

## US export control

**Not subject to the EAR at all** — a stronger position than being subject to it
and classified as EAR99.

15 CFR 734.3(b)(3) places published software outside the EAR; 734.7 defines
publication to include "posting on the Internet on sites available to the
public". The one carve-back, 734.7(b), applies to **encryption software under
ECCN 5D002**. Reveille implements no cryptography, so it never engages.

No notification is required, and none of the BIS/NSA encryption notification
machinery applies. **Do not describe this project as "EAR99"** — that would
concede it is subject to the EAR when it is not.

Re-run this analysis if cryptographic functionality is ever added.

## EU accessibility

The **European Accessibility Act** (Directive (EU) 2019/882) does not apply: its
Art. 2 scope is a closed list of products and services that does not include
developer tooling, and Art. 3(15)'s commercial-activity filter applies here too.
Note the EAA contains **no open-source carve-out at all** — the reason this
project is outside it is scope and commerce, not a FOSS exemption.

**EN 301 549** is worth reading precisely. Clause 11.0, NOTE 4 states that "the
accessibility of command line interfaces is not dealt with in the present
document" — so the CLI is expressly outside the harmonised standard. What *does*
map is **clause 10, "Non-web documents"**, which covers downloadable documents:
the generated HTML report.

That is where the accessibility work belongs and where it has been done — the
report targets WCAG 2.1 AA, with contrast, table semantics, ARIA labelling and
`prefers-reduced-motion` support. Voluntary, and worth doing on its merits.

## India — DPDP Act 2023

The maintainer is based in India, and s.3(a) applies the Act to processing within
India **without** requiring the data subject to be in India. The relevant
processing here is contributor data, not user data — the tool sends nothing
anywhere.

The mitigation is structural rather than procedural: contributor licence
acceptance is recorded as a tick in a pull request plus a `Signed-off-by`
trailer, both data the contributor publishes themselves. **No register is kept,
no database, no third-party service.** See [PRIVACY.md](../PRIVACY.md).

## Liability posture

What actually limits exposure, in order:

1. **Apache-2.0 §§7–8** — the warranty disclaimer and limitation of liability.
   These are contract terms binding every user, and they cost nothing. Note both
   self-limit: §8 excepts what "applicable law" requires.
2. **Not promising anything.** An express public claim about accuracy or fitness
   is how an express warranty gets created that §7 did not disclaim. The
   documentation therefore avoids warranty-flavoured language, and states what
   the figures do *not* measure at least as prominently as what they do.
3. **Apache-2.0 §9** — anyone offering paid support on top of Reveille acts "on
   their own behalf and on their sole responsibility", not the maintainer's.
4. **Staying non-commercial**, which is the gate for both the CRA and the PLD.

## Sources

Regulation texts were read from the EU Publications Office; US CFR text from the
eCFR; Apache-2.0 from apache.org; EN 301 549 from ETSI. Where a source could not
be reached or a question could not be settled, this document says so rather than
filling the gap.

**Restating the disclaimer: research, not legal advice.** The points most worth
professional review, if this ever becomes commercial, are the CRA's undefined
threshold for "donations exceeding the costs", and trademark clearance on the
name "Reveille", which is a common English word with pre-existing commercial uses.
