# 0007 — The licence moves from MIT to Apache-2.0

**Status:** Accepted

## Context

Reveille shipped versions 0.1.0 through 0.7.0 under the MIT Licence. Nothing
about that was broken: MIT is OSI-approved, permissive, and one of three stated
advantages over the commercial Bitbucket Marketplace alternatives — free and
permissively licensed, alongside being the only real calendar view for Bitbucket
Cloud and needing no admin approval to install.

So the question was never "is MIT failing", it was whether a different permissive
licence would serve better before the project acquires outside contributors.

Two constraints were checked and are clear:

- **Sole copyright holder.** Every commit touching `src/` and `tests/` is by one
  person. The two identities in `git shortlog` are the same author under a gmail
  address and a GitHub noreply address — the exact case Reveille's own noreply
  folding handles. `dependabot[bot]` only bumps dependency metadata.
- **No dependency constrains the choice.** All 25 runtime packages are permissive:
  MIT, BSD-2/3-Clause, ISC, PSF-2.0, `Apache-2.0 OR BSD-2-Clause`, and
  `python-dateutil`'s Apache/BSD dual licence. **Zero copyleft, and specifically no
  GPL-2.0-only package**, which is the one combination Apache-2.0 would have made
  awkward.

Copyleft was considered and rejected. AGPL's network clause is inert here — Reveille
is a local offline CLI, so there is no service to trigger it — while the adoption
cost against an audience of enterprise Atlassian shops, many of which ban AGPL
outright, is entirely real. Full cost, no protection. Source-available licences
additionally forfeit the OSI classifier and inclusion in distributions and
awesome-lists.

## Decision

**The licence is Apache-2.0 from 0.8.0 onward.** Versions up to and including 0.7.0
remain MIT permanently; relicensing is prospective only, and anyone may still take
those versions under MIT from the Git history.

Apache-2.0 provides three things MIT does not:

- **§3, an express patent grant.** MIT has none, and whether it implies one is
  contested. Reveille's own patent surface is close to nil — it reads `git log` and
  draws charts — so this matters less for the code than for the signal it sends to
  a corporate legal review.
- **§5, inbound equals outbound.** A pull request is automatically licensed under
  the project's terms, with no contributor licence agreement to administer. This is
  the reason to act **now** rather than later: §5 reaches only contributions received
  after the change, so every month of delay is a contribution it cannot cover.
- **§6, an explicit trademark non-grant.** A fork cannot present itself as this
  project. MIT is silent on the point.

`NOTICE` is deliberately **not** created. §4(d) is conditional — the obligation binds
downstream redistributors only *if* the work includes such a file. Reveille vendors
nothing and has one copyright holder, so a NOTICE file would carry no attribution
that needs carrying, while permanently obliging every downstream fork to propagate
it. The Apache Software Foundation's own guidance is to keep NOTICE minimal and add
nothing not legally required; here that amount is nothing. Note also that the ASF's
mandatory-NOTICE rule is internal ASF policy and expressly does not apply to
projects outside the foundation.

Every source file carries a two-line SPDX header rather than the full boilerplate,
so a file separated from this repository still declares its licence. Formal
[REUSE](https://reuse.software) conformance was considered and declined: it would
require covering every asset and config file and maintaining a `LICENSES/` directory
duplicating `LICENSE`, for no benefit any consumer has asked for.

## Consequences

**What this costs.** Apache-2.0 §4(b) requires anyone distributing modified files to
carry prominent notices stating they changed them. MIT imposes nothing comparable, so
forking is marginally higher friction. And Apache-2.0 is incompatible with **GPLv2**
(compatible with GPLv3), so Reveille's source can no longer be copied into a
GPLv2-only project. For an end-user CLI rather than a library, that is a narrow door
to close, but it does close.

**What it does not cost.** Nothing about installation, distribution, or use changes.
Apache-2.0 is OSI-approved and permissive; the PyPI classifier remains an
OSI-approved one.

**A packaging caveat.** PEP 639 deprecates licence classifiers in favour of an SPDX
`License-Expression` field, which requires Poetry ≥ 2.2 and the `[project]` table.
This project builds with Poetry 1.8.2, which emits neither, so the classifier stays
for now — dropping it would leave the distribution with no structured licence
metadata at all. Moving to `license = "Apache-2.0"` with `license-files` is a
follow-up tied to the Poetry upgrade, not to this decision.

**Guards.** `make check-licence` asserts `LICENSE`, `pyproject.toml` and
`reveille.__licence__` agree; `tests/unit/test_licence.py` asserts every source file
carries an SPDX header naming the same licence, and that the classifier does not
contradict it. Before this record there was no guard at all on `__licence__`, which
could have drifted from `LICENSE` indefinitely and silently.

**This is a decision recorded, not legal advice.** The analysis behind it was
research from primary sources by someone who is not a lawyer.
