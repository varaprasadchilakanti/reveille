# Regulatory position

**This is a record of research, not legal advice, and it was not written by a lawyer.** Each
conclusion below names the provision it rests on, so a reader who disagrees knows where to push.

In short: the GDPR engages and the maintainer is neither controller nor processor
under it; Reveille is out of scope for every other regime examined. The Cyber Resilience Act and
Product Liability Directive conclusions depend on the software being supplied outside the course
of a commercial activity.

---

## What the software does

Every conclusion depends on these facts:

- It runs entirely on the user's own machine: no telemetry, no server, no account. It makes no
  outbound call, and the maintainer never receives anything. It runs Git, with signature checking,
  fsmonitor and (for `state`) repository-defined content filters switched off. Git obeys the
  repository's other `.git/config` settings; see the Threat Model in [SECURITY.md](../SECURITY.md).
- It reads commit metadata (object name, author name and address, timestamp), the
  `Co-authored-by` trailers (names and addresses of people credited), and, per file in each
  commit, the **path and the number of lines added and deleted**, as `git log --numstat` reports
  them; for `reveille state`, the working tree's paths and their status letters, the current
  branch name and worktree directories (which can contain a login name). Reveille receives
  paths, counts and status letters; Git reads the files to compute them. It reads no source code,
  no other part of any commit message, and no diff content.
- It contains no machine learning and no model. Every number is arithmetic over commit counts,
  lines and dates.
- It is supplied free of charge and outside any commercial activity: no paid tier, hosted
  version, paid support or donation scheme.

## GDPR — Regulation (EU) 2016/679

Commit author names and email addresses are personal data under Art. 4(1), and reading them is
processing under Art. 4(2). The question is who is responsible for it.

A controller "determines the purposes and means of the processing" (Art. 4(7)). The maintainer
determines neither: the user chooses a repository, runs the command, and decides what to do with
the report. A processor "processes personal data on behalf of the controller" (Art. 4(8)); the
maintainer processes nothing, because no data reaches them.

The maintainer is therefore neither controller nor processor for the tool's operation. The user
is the controller. Which lawful basis applies, and whether any employment or works-council rule
applies, is for that controller to determine; this document does not answer it. Recital 78 only
says software producers "should be encouraged" to consider data protection in design, while
Art. 25's binding obligations fall on the controller.

For you as a user: the generated report contains contributor names and email addresses. If you
circulate it, you are handling personal data, and that is your responsibility, not the tool's.
`--exclude-author` removes a person, matching the value you give plus every identity a `.mailmap`
ties to it, and warns on stderr if it matched nothing.

## EU Cyber Resilience Act — Regulation (EU) 2024/2847

Out of scope, on the commercial-activity test. Art. 3(22) defines "making available on the
market" as supply "in the course of a commercial activity, whether in return for payment or free of
charge", so being free is not the exemption; being non-commercial is. Recital 18 says free and
open-source software not monetised by its maintainer is not supplied in the course of a commercial
activity, and that regular releases do not by themselves imply commerce. Recital 20 adds that
hosting on a package manager is not, by itself, placing on the market, so publishing to PyPI
does not change the position. The "open-source software steward" regime (Art. 3(14)) does not
apply: a steward must be a legal person.

Timeline: Art. 14 reporting obligations have applied since 11 September 2026 and Chapter IV
since 11 June 2026; full application is 11 December 2027.

## Product Liability Directive — Directive (EU) 2024/2853

Out of scope, through the same test. Art. 2(2) excludes free and open-source software developed
or supplied outside the course of a commercial activity, and Recital 14 confirms that providing
such software on open repositories is not making it available on the market unless that occurs
commercially. The Directive applies to products placed on the market after 9 December 2026.
The liability is strict, so a warranty disclaimer is no defence under it.

## EU AI Act — Regulation (EU) 2024/1689

Not an AI system, so the Regulation does not engage. Art. 3(1) turns on a system that "infers,
from the input it receives, how to generate outputs". Recital 12 says the definition "should not
cover systems that are based on the rules defined solely by natural persons to automatically
execute operations", and that the capacity to infer must "transcend basic data processing".
Counting commits and applying human-authored thresholds is rules defined by natural persons: no
model, no learning, no adaptiveness.

Reveille is not an AI system: every figure is fixed arithmetic. If you feed its output into a model or AI agent that ranks, scores or selects people at work, that system is yours, and it may be high-risk under Annex III point 4 of the EU AI Act.

An employer using the opt-in ranking to evaluate workers would be doing what Annex III
point 4(b) lists as high-risk for AI systems: "to monitor and evaluate the performance and
behaviour of persons" in work relationships. The figures measure the volume and regularity of
commits, not anyone's performance; they are not fit for that use. The score, tier and designation are off by default
([ADR 0010](adr/0010-ranking-is-opt-in.md)). The JSON and CSV outputs still carry a `rank`
column, in table order: by commits, or by score with `--ranking`.

## US export control

Not subject to the EAR. 15 CFR 734.3(b)(3) places published software outside the EAR, and
734.7 defines publication to include "posting on the Internet on sites available to the public".
The one carve-back, 734.7(b), applies to encryption software under ECCN 5D002. Reveille implements
no cryptography, so it never engages, and no BIS/NSA encryption notification applies.

## EU accessibility

The European Accessibility Act (Directive (EU) 2019/882) does not apply: its Art. 2 scope is a
closed list of products and services that does not include developer tooling, and Art. 3(15)'s
commercial-activity filter applies here too. The Act has no open-source carve-out; scope and
commerce are the reasons.

EN 301 549 clause 11.0, NOTE 4 states that "the accessibility of command line interfaces is not
dealt with in the present document", so the CLI is outside the harmonised standard. Clause 10,
"Non-web documents", maps to the generated HTML report. The report is built to WCAG 2.1 AA, with
contrast, table semantics, ARIA labelling and `prefers-reduced-motion` support, and a test checks
the palette's contrast. No conformance audit has been done.

## India — DPDP Act 2023

The maintainer is based in India, and s.3(a) applies the Act to processing within India without
requiring the data subject to be there. The Act's substantive sections commence on the
government's phased timetable. The relevant processing is contributor data, not user
data; the tool sends nothing anywhere. Contributor licence acceptance is recorded as a tick in a
pull request plus a `Signed-off-by` trailer, both published by the contributor. No register, no
database, no third-party service is kept. See [PRIVACY.md](../PRIVACY.md).

## Liability

Apache-2.0 §§7-8 disclaim warranty and limit liability as far as applicable law allows; §8 itself
excepts what "applicable law" requires. Under §9, anyone
offering paid support on top of Reveille acts "on their own behalf and on their sole
responsibility".

## Sources

Regulation texts were read from the EU Publications Office; US CFR text from the eCFR; Apache-2.0
from apache.org; EN 301 549 from ETSI. Where a source could not be reached or a question could not
be settled, this document says so.

This is research, not legal advice.
