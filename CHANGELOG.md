# Changelog

All notable changes to Reveille are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning 2.0](https://semver.org/).

From 0.8.0 a release heading carries three things — the version, the release
date, and the theme: `## [X.Y.Z] — YYYY-MM-DD — Theme`. The theme is reused
verbatim as the GitHub Release title, so the two can never drift. Headings
before 0.8.0 predate the convention and are left as they were released.

---

## [Unreleased]

Nothing yet.

---

## [0.8.0] — 2026-09-03 — Security Hardening, Apache-2.0, and a Corrected Report

### Added

- **A five-axis repository profile.** Spread, Continuity, Currency,
  Revisiting and Small steps, each a **naturally bounded share** — a count of
  something out of a count of something — so no axis is rescaled by a constant
  chosen to make the shape look right. That constraint is the design: a radar
  whose axes are normalised by invented factors can be given any silhouette
  its author wants, and a reader has no way to tell.

  The form is used with its weaknesses stated rather than hidden. A radar
  encodes by **area**, which Cleveland & McGill (*Graphical Perception*, JASA
  1984) rank far below position and length for accuracy, and the enclosed area
  depends on the **order** of the axes, which carries no meaning — permuting
  two changes the silhouette without changing a number. So the order is fixed
  in `AXIS_ORDER` and never data-dependent, every vertex carries its own value
  as text so the figure reads as five numbers, the radial axis is a true 0–1,
  and the report says all of this under the chart.

  No axis is a target and none measures a person. A finished library scores
  low on most of them, for entirely ordinary reasons.

- **File-level analysis: where change concentrates, and what kind of file it
  lands in.** Two sections, both about paths and neither about people.

  `git log --numstat` was already carrying a path on every line, and the
  per-commit totals were being summed out of a structure that had them and
  then discarded. **This costs no additional Git work** — only parsing already
  paid for — so the single-pass read that 0.7.0 made 9.4× faster is untouched.
  Totals accumulate while streaming, bounded by the number of distinct paths
  rather than by commits multiplied by the files each touched; a
  50,000-commit repository would otherwise hold a path list per commit for the
  whole run.

  *Where Change Concentrates* ranks paths by churn — added plus deleted, not
  net, because a file that gains and loses a thousand lines has been worked
  on. This is the churn axis of hotspot analysis (Tornhill, *Your Code as a
  Crime Scene*, 2013), resting on relative code churn (Nagappan & Ball, ICSE
  2005). The full method crosses churn with complexity; Reveille reads history
  and never file content, so it reports the churn axis alone and says so. A
  file that changes often is one to look at, not one that is wrong.
  Machine-generated files are excluded — `poetry.lock` is the largest single
  source of changed lines in this repository by a factor of three, and tells a
  reader nothing they can act on — but their churn still counts in the type
  breakdown, since excluding a file from a ranking is not the same as hiding
  it.

  *Change by File Type* totals churn by extension, so a window can be
  described as source, tests, documentation or configuration without naming a
  file or a person. Extensions beyond the largest eight are pooled rather than
  dropped, so the total is preserved. A dotfile such as `.gitignore` is a file
  called gitignore, not a gitignore-typed file, and is reported as having no
  extension.

  Renames resolve to their destination. Counting both sides would double a
  file; counting the source would attribute churn to a path that no longer
  exists.

- **A change-size histogram.** How much each commit changed, pooled across the
  history, in log-spaced buckets — linear buckets over a range spanning one
  line to ten thousand put almost every commit in the first bar and state
  nothing. This is relative code churn in the sense of Nagappan & Ball, *Use
  of Relative Code Churn Measures to Predict System Defect Density* (ICSE
  2005), and it shows the working rhythm: many small steps or a few large
  ones. Churn is added **plus** deleted, not net — a commit that deletes five
  hundred lines is a large change. Like the Lorenz curve it pools the commits
  and separates no contributor out.

- **[`docs/PLAYBOOK.md`](docs/PLAYBOOK.md)** — one page on how to *read* a
  report, as distinct from how to produce one. The order to take the sections
  in, a table of what each measure supports and what it does not, three
  questions Reveille answers well and three it answers badly, and the rules an
  agent should follow when summarising a report: ask `capabilities` rather
  than guess, branch on the exit code, check `schema_version`, pass
  `--deterministic` for anything compared, and never name an individual the
  default report does not name. Linked from the README and `llms.txt`; it
  states use and links rather than restating the reference.

- **A written summary of what the history shows**, at the top of the report.
  Five rules over figures that already appear further down — the size and span
  of the history, how commits are distributed, the rhythm of committing,
  weekend share, and dormancy — each a sentence carrying the figure it rests
  on.

  This is data-to-text generation in the sense of Reiter and Dale, *Building
  Natural Language Generation Systems* (2000): content selected by thresholds
  and realised through fixed templates. **There is no model and no network
  call**, and the same history always produces the same sentences, so
  `--deterministic` still holds — recency measures against the last commit
  rather than the wall clock for exactly that reason.

  What it refuses to do is the point. It names no one and quotes no address,
  asserted by a test that searches the generated prose for every contributor's
  name and email. It carries no evaluative vocabulary: a second test fails the
  build if *healthy*, *risk*, *productive*, *concerning* or a dozen others
  appear. And it withholds rather than computes — below twenty commits there
  is no cadence finding, because a median over a handful of days is arithmetic
  and not evidence.

  One rule was wrong as first written and the tests caught it. The Gini
  coefficient is bounded by (n−1)/n, so over two contributors it cannot exceed
  0.50 however lopsided the split; a raw threshold produced "commits are spread
  fairly evenly… the busiest holding 73%" in a single sentence. The wording now
  follows the leading share, with the coefficient reported as the evidence
  behind it.

- **The pinned Poetry moves from 1.8.2 to 2.4.2**, closing a mismatch that
  contributed to the incident this release opened with. Tested before adopting:
  all 452 tests pass, and the lock regenerates with **zero package version
  changes** — 51 packages before and after, a pure format migration.

  Three concrete gains, each of which was blocked on this and nothing else:

  - **`poetry check` runs at all.** Under 1.8.2 it failed on the bundled
    classifier list predating `Programming Language :: Python :: 3.14`, which is
    why `make check-lock-sync` had to use the narrower `poetry lock --check`.
    That command was *removed* in 2.x; the target now uses `poetry check --lock`
    and audit finding #20 is closed rather than half-closed.
  - **The lock format now matches what Dependabot writes.** Dependabot
    regenerated with a modern Poetry and produced `lock-version 2.1`, while local
    tooling wrote `2.0` — so its pull requests flipped the file between two
    formats, which is precisely the churn that produced a conflict nobody could
    resolve correctly. Both sides now write `2.1`.
  - **`SOURCE_DATE_EPOCH` is honoured**, which 1.8.2 silently ignored.

  **This requires Poetry ≥ 2.2 locally.** If Poetry came from a distribution
  package, `poetry self update` will fail with a permission error — it cannot
  write into a system-managed directory, and forcing it with `sudo` would fight
  the package manager. Install it user-scope instead, which shadows the system
  copy without removing it:

  ```console
  $ pipx install "poetry==2.4.2"
  ```

  The `build-system` floor moves with it, from `poetry-core>=1.0.0` to
  `>=2.0,<3.0`. That is not cosmetic: anyone building from the sdist resolves
  poetry-core by that constraint, and 1.x emits Metadata 2.1 without
  `License-File`, ignores `SOURCE_DATE_EPOCH`, and would therefore produce a
  different artefact from the one CI verifies as reproducible. Verified by
  installing the built sdist and wheel into clean virtual environments:
  Metadata 2.4, `License: Apache-2.0`, `License-File: LICENSE`, and the CLI runs.

- **Supply-chain and workflow hardening: four additions, each closing a distinct
  gap.**

  **`zizmor`** analyses the workflows themselves. Pinning every action to a SHA
  stops a mutable tag being repointed at malicious code; it does nothing about
  what our own workflows do with untrusted input — template injection into a
  `run:` block, an over-broad token, a `pull_request_target` checking out fork
  code. None of those involve a third-party action at all.

  **`actionlint`**, as a pre-commit hook, covers correctness where zizmor covers
  security: unknown contexts, malformed matrices, expression type errors.
  Verified discriminating — an undefined context is reported with an exact line
  and column.

  **`osv-scanner`** gates both CI and the release. Not redundant with Dependabot,
  for a structural reason rather than a data one: Dependabot alerts are an
  asynchronous platform service, not a workflow step, so they cannot block
  anything. The release-time scan catches an advisory published between the merge
  and the tag. `pip-audit` was rejected because it cannot read `poetry.lock` —
  upstream closed that as not planned — so it would scan an exported file rather
  than the lock that ships.

  **The SBOM is now attested.** A plain attached file has no cryptographic
  binding to the run that produced it and can be swapped; this binds it to the
  workflow identity using the same Sigstore model the distributions already rely
  on through PEP 740.

- **Build reproducibility is now verified in CI** — two builds of the same commit
  must produce identical bytes.

  `SOURCE_DATE_EPOCH` is derived from the analysed commit, the same convention
  the `--deterministic` report flag uses, so a build and a report cut from one
  commit agree on what "now" means. It is set because it is *measurably*
  honoured on the pinned Poetry 2.4.2 — wheel entry timestamps track the value
  exactly. On the previously pinned 1.8.2 it was inert, pinning entries to
  `(1980, 1, 1)` regardless, and setting it there would have looked meaningful
  while doing nothing.

  The job still builds twice and compares rather than trusting the mechanism.
  Poetry falls back to a fixed date when the variable is absent, so a build can
  be reproducible for the wrong reason; only comparing two builds shows whether
  the property actually holds.

- **`RELEASE.md`** — the release procedure, which existed only in gitignored notes.
  A project with a PyPI Trusted Publisher and PEP 740 attestations had no written
  release process in the repository at all: the tag ceremony, what the publish
  workflow does, how to verify from the published artefact rather than the source
  tree, and how to recover a bad release (yank and re-publish; never delete — a
  filename can never be reused). It also names the three repository settings the
  release path depends on, which live on GitHub and are easy to lose.

- **Architectural fitness functions** — `tests/unit/test_architecture.py`. Tests
  whose subject is a *structural property* rather than a behaviour, so the build
  fails when the shape stops holding rather than when a feature breaks. The term
  is from Ford, Parsons and Kua, *Building Evolutionary Architectures* (2017),
  and `docs/ARCHITECTURE.md` now names it alongside the other lineage this design
  borrows.

  Nine properties, each written against the AST rather than a text search — a
  structural check built on `grep` matches comments and docstrings, so it can
  pass while the property it names is false. The offline guarantee stated
  structurally (nothing capable of opening a socket is imported anywhere, which
  is a stronger claim than "this run made no request"); no dynamic import or
  subprocess, which would be a way back out to the network the import check
  cannot see; the direction of first-party imports, resolved through relative
  imports as well as absolute ones; the read-only guarantee (only the renderer
  and `init` may write to disk, including through `Path.open` and GitPython's
  dynamic command dispatch); the exit-code contract (no literal code, so a
  fourth cannot widen a published contract unnoticed); that the exit-code enum
  defines exactly the three published codes; and completeness of the
  configuration surface.

  Ruff's `mccabe` complexity limit is now stated explicitly rather than inherited
  from the tool's default. It was already active and caught three genuine cases
  during this release, each resolved by extracting a function rather than raising
  the ceiling.

- **A Lorenz curve and Gini coefficient, replacing an ad-hoc concentration
  number.** The default report now shows how evenly commits are distributed
  across contributors — the cumulative share of commits against the cumulative
  share of contributors, plotted against a diagonal of perfect equality.

  Both are borrowed deliberately. The Lorenz curve (1905) and the Gini
  coefficient (1912) are the standard instruments for concentration in a
  population, and a century of interpretation *and of documented weakness* comes
  with them. What they replace — "how many contributors account for a majority of
  commits" — had no literature behind it, no defined range, and a step change in
  value whenever one contributor crossed half.

  Crucially, neither names anybody, and the curve is unchanged by who sits where
  in it. It answers a question about the repository, which is why it stays in the
  default report while the per-person ranking does not.

  The report states the limits beside the chart: a high value is not a fault and
  a low one is not a target, a single-maintainer project scores 0 by definition,
  and the maximum for a sample of *n* contributors is `(n-1)/n`, so the number is
  comparable against this repository over time and not against a different one.

- **A Contributor Licence Agreement, and a `PRIVACY.md`.** Contributions are now
  accepted under [`CLA.md`](CLA.md) version 1.0, alongside a Developer Certificate
  of Origin sign-off. The CLA grants the rights, including the ability to offer
  the project under an additional licence later; the DCO certifies provenance per
  commit. Recorded as [ADR 0009](docs/adr/0009-contributor-licence-agreement.md),
  which also narrows the claim in ADR 0007 that Apache-2.0 §5 left nothing to
  administer — §5 carves out "any separate license agreement you may have
  executed with Licensor", which is what this is.

  The text is adapted from the Apache ICLA v2.2 under the ASF's express reuse
  permission, with all Apache references removed and the derivation noted as that
  permission requires, plus the outbound-licence clause from the Harmony
  Agreements under CC BY 3.0. It carries a floor the ICLA does not: whatever else
  the project is later licensed under, contributions stay available under the
  licence in force when they were made.

  **Acceptance collects nothing.** A contributor ticks a box in the pull request
  and signs off their commits — both data they publish themselves — and a CI job
  verifies it and writes nothing. There is no signatures file, no database, and
  no third-party service, which is deliberate: a signature register would make
  the maintainer a data controller for a set of names and addresses, and a
  committed one could never be erased from anybody's clone.

  `PRIVACY.md` states what the tool does with data (nothing leaves your machine),
  what the *report* contains (contributor names and email addresses, which makes
  whoever circulates it responsible for it), and what the project holds about
  contributors.

- **`reveille capabilities`** — a description of what the tool can and cannot do,
  in plain text or JSON. Written for a program as much as a person: an agent or a
  script can ask the installed binary directly instead of inferring from a README.

  The document is deliberately split. The version, the output schema version, the
  commands with their options and the exit-code contract are **read from the
  running program**, so they cannot drift from it — this project has already
  shipped a README documenting a subcommand that never existed, and a
  machine-readable description written by hand would rot the same way. What
  cannot be derived — what the tool is *for*, what it refuses to claim, and the
  caveats that change how a number should be read — is stated once and tested for
  completeness.

  The `cannot` list is the load-bearing half. It says in machine-readable form
  that Reveille does not measure productivity, performance, contribution value or
  code quality; that it is not fit for performance review, compensation,
  promotion, redundancy or hiring decisions; that commit concentration is not a
  bus factor; that it reads no source code, only commit metadata; and that
  cross-repository per-person aggregation was cut deliberately rather than left
  undone. A tool that advertises only its strengths is one an agent will misuse.

- **The JSON output now records its own provenance.** A report stated numbers without
  stating what produced them, so two reports that disagreed could not be reconciled.
  JSON output now carries a `provenance` block: the Reveille version, the analysed
  HEAD commit SHA, whether a `.mailmap` was applied, whether ranking was enabled and
  under which weights, and the filters **as requested** — `requested_branch`,
  `requested_since`, `requested_until`, `exclude_authors`, `min_commits`. The
  distinction matters: `analysis_since` records where the window began, while
  `requested_since` records whether anyone asked for it, and without both a reader
  cannot tell "the full history, which starts in March" from "filtered to start in
  March". Ranking weights are `null` when ranking is off, because reporting weights
  that were never applied would be a false statement.

- **`schema_version`, as the first key in the JSON document**, so a consumer can
  decide whether it can parse the rest before trying. It starts at `1.0` and is
  independent of the release version. v0.7.0 renamed `derived.bus_factor` to
  `derived.commit_concentration` and a pipeline reading the old key got a `KeyError`
  with no way to tell which shape it had been handed; this is the last output change
  that will be undetectable.

- **`--deterministic`, producing byte-reproducible output.** Verified for both HTML
  and JSON: two runs over an identical repository produce identical bytes. It pins
  `generated_at` to the analysed HEAD commit's timestamp, the way a reproducible
  build pins to `SOURCE_DATE_EPOCH`, and closes the analysis window on the last
  commit rather than on `date.today()` — otherwise the ranking's recency component
  still varies with the clock. **It therefore changes scores, not merely bytes**,
  which is why it is opt-in and why provenance records that it was used.

- **`make check-lock-sync`**, asserting `poetry.lock` still agrees with
  `pyproject.toml`, wired into CI. This is what audit finding #20 actually asked for.
  `make check-lock` answers a different question — whether the file parses at all —
  and a lock can be perfectly valid TOML while describing a dependency set nobody
  asked for.

- **`poetry.lock` can no longer be merged textually.** `.gitattributes` marks it
  `-merge`, so Git keeps the current branch's version and declares a conflict instead
  of writing conflict markers into a generated file. "Keep both sides" is never a
  valid resolution for a lock file, but it is the natural gesture in a conflict
  editor; removing the markers removes the gesture. Verified by replaying the original
  merge: the conflict is still raised, no markers are written, and the retained file
  still parses.

- **`make check-lock`, and a CI job that runs before anything installs.** The
  `lockfile` job validates the lock using only the standard library, and `lint`,
  `typecheck` and `test` all depend on it. The gate deliberately avoids Poetry: an
  unreadable lock is exactly what stops Poetry running, so a check that needed it
  could never report the failure it exists to catch. The release SBOM job validates
  the lock too, since `SECURITY.md` promises the SBOM is byte-reproducible from it.

- **`make check-licence`**, asserting `LICENSE`, `pyproject.toml` and
  `reveille.__licence__` agree. There was previously no guard on `__licence__` at all.

- **Every source file carries a two-line SPDX header**, including the report template,
  so a file still declares its licence and copyright holder if it is ever separated
  from this repository.

- **Workflow hardening**: `persist-credentials: false` on all eight `actions/checkout`
  steps, `timeout-minutes` on every job (GitHub's default is 360), and concurrency
  groups on `ci.yml` and `codeql.yml` — deliberately not on `publish.yml`, where
  cancelling a half-finished publish is worse than letting two run.

- **Dependency updates are grouped into one pull request per ecosystem.** Ungrouped,
  26 dependency PRs merged between v0.7.0 and this release, and every merge was an
  opportunity to hand-resolve a `poetry.lock` conflict — which is what broke `main`.

- **`.github/PULL_REQUEST_TEMPLATE.md`**, whose "Verified" section asks what was run
  and what it showed, and reminds the author to break any new guard and watch it fail.

- **182 new tests, taking the suite from 355 to 537.** Eleven new files carry 178
  of them: thirty-one security regression tests, twenty-six on the capability
  document, twenty-five on the Lorenz curve and Gini coefficient checked against
  values the definitions fix, twenty-three on provenance, schema version and
  determinism, seventeen on the ranking default across all three output formats,
  fourteen on chart colour assignment, fourteen on commit concentration, nine
  architectural fitness functions, nine on the CLA gate, six on licence
  declarations, and four on lock integrity. The remaining four extend existing
  files. Each was observed failing against the defect it guards before being
  trusted.

### Changed

- **The contributor ranking is off by default.** `--ranking` turns it on;
  `--no-ranking` still works, so no existing invocation breaks. This is a
  **breaking change to default output in every format**, and it is the intended
  cost — the previous default was the problem.

  Every release since 0.6.0 added a caveat around this feature rather than
  changing it: that the weights are a judgement not a derived model, that it
  measures volume and regularity of commits rather than contribution or value,
  that DORA and SPACE both say such measures must not be applied to individuals.
  All true, and none of it changed what a person saw when they ran the command —
  a report opening with named individuals ranked by score and labelled with a
  military rank. Documentation does not travel with the artefact, and the HTML
  report is designed to be forwarded. Recorded as
  [ADR 0010](docs/adr/0010-ranking-is-opt-in.md).

  When ranking is off, `tier`, `tier_designation`, `composite_score` and
  `percentile` are **absent** from the JSON rather than present with sentinel
  values. `"tier": 0` is a number a consumer can mistake for data; an absent key
  cannot be. `provenance.ranking.enabled` says which shape to expect.

- **The licence moves from MIT to Apache-2.0.** Versions up to and including 0.7.0
  remain MIT permanently — relicensing is prospective only, and those versions stay
  available under MIT from the Git history. Apache-2.0 adds three things MIT does not:
  an express patent grant (§3), an automatic inbound-equals-outbound rule for
  contributions (§5) so a pull request needs no contributor licence agreement, and an
  explicit trademark non-grant (§6). The cost is real but narrow: §4(b) requires
  modified files to carry change notices, and Apache-2.0 is incompatible with GPLv2
  (though compatible with GPLv3). Checked first: all 25 runtime packages are
  permissive, with zero copyleft and no GPL-2.0-only dependency. Recorded as
  [ADR 0007](docs/adr/0007-apache-2-0-licence.md). No `NOTICE` file is created —
  §4(d) binds downstream only if one exists, and Reveille vendors nothing that needs
  attributing.

- **`metadata.default_branch` is renamed to `metadata.analysed_branch`, and now holds
  the right value.** This is a **breaking JSON key change**. The old field held
  neither the default branch nor the analysed one: it was recomputed from whatever was
  checked out, ignoring `--branch`. A report generated with `--branch main` from a
  feature checkout named the feature branch, in the JSON and in the HTML, which renders
  it as "Branch:". On `main` all three meanings coincide, which is why it survived to
  v0.7.0. Accepted pre-1.0 on the same reasoning as
  [ADR 0005](docs/adr/0005-commit-concentration-not-bus-factor.md). Recorded as
  [ADR 0008](docs/adr/0008-output-provenance-and-schema-version.md).

### Fixed

- **The default report named an individual and called them "Top Contributor".**
  Found by a legal review of the artefact, not of the documentation. The fifth
  summary card was never gated on `provenance.ranking_enabled`: `--no-ranking`
  removed the rank column, the designation and the score, and then printed a
  named person under a superlative at the top of the page — the visible first
  name, and the full name to assistive technology. ADR 0010 says the default
  report describes the repository and names nobody, and this card was the one
  place it did not. The slot now carries the Gini coefficient instead, which
  is a repository-level figure and the one the distribution section is built
  on.

- **Screen-reader users were told the table was a ranking in both modes.** The
  visible heading switched correctly between "Contributor Rankings" and
  "Contributors"; the table's visually-hidden `<caption>` said "Contributor
  rankings" unconditionally. One class of reader was told the opposite of
  another.

- **Every report was subtitled "Repository Performance Report".** The project
  spends its documentation declining to call this a performance measure, and
  then asserted it in the artefact, in the line directly under the repository
  name. It now reads "Repository History Report".

- **The generated findings described a working pattern in teams too small to
  hide anyone.** Omitting a name does not make a sentence non-personal: GDPR
  Recital 26 asks whether a person can be *singled out* by any means
  reasonably likely to be used, and in a two-person repository "31% of commits
  were authored at a weekend" identifies somebody at zero cost — to their own
  colleague, and to anyone the report is forwarded to, with the contributor
  table four sections below completing it. Behavioural findings are now
  withheld below three contributors: the weekend finding entirely, and the
  leading-share clause of the distribution finding, which keeps the Gini.
  Volume and recency describe the repository at any size and are unchanged.

- **Two contributors sharing a display name collapsed into one, differently in
  each chart.** ADR 0002 makes the lowercased email the identity key, but the
  charts labelled by display name, which is not unique. Plotly then resolves a
  repeated category label differently per trace type: a bar chart collapses
  the bars onto one category, a pie sums the slices, a line chart draws two
  legend entries a reader cannot tell apart. Measured against this repository
  before its `.mailmap` existed — 201 commits under one address and 1 under
  another — the table said 201 and 1, the bar chart said 201, and the pie said
  202.

  A `.mailmap` fixes the case of one person under two addresses. It is the
  wrong tool for two genuinely different people who share a name, and most
  repositories have no `.mailmap` at all, so the charts are now correct
  without one: a name occurring once is drawn as it is, and a name occurring
  more than once carries the address that distinguishes it. The map is built
  over every contributor rather than the subset a given chart draws, so one
  identity keeps one label across the legend, the bars, the pies and the
  heatmap menu.

- **The ranking opt-in was real only in JSON; the two formats people read still
  ranked them.** `--ranking` defaults off in this release, but the HTML template
  and the CSV writer both gated on `ranked_contributors` being non-empty — and
  that list is populated with placeholder rows either way, so it was never the
  gate. The default report therefore still opened a section headed **"Contributor
  Rankings"**, printed a rank number against every named individual, and carried a
  screen-reader caption stating the rows were "ordered by composite score" when
  every score was `0.0` and the real ordering was by commit count. The CSV — the
  format most likely to be opened in a spreadsheet and sorted — still emitted
  `tier`, `composite_score` and `percentile` as zeroes, one function below the
  JSON writer that omits them on purpose and explains why in a comment.

  All three formats now branch on `provenance.ranking_enabled`. With the ranking
  off the table is headed "Contributors", loses its rank, designation and score
  columns, and says it is ordered by commit count; the CSV omits the same four
  fields JSON omits. The underlying figures are untouched — opting out of the
  ranking does not cost anyone their commit counts. `tests/unit/adapters/
  test_ranking_presentation.py` asserts this across all three formats in both
  directions.

- **`reveille init` scaffolded the opposite of the new default.** The generated
  `reveille.toml` said *"Set to false to omit the contributor ranking table"* over
  a commented `enabled = true` — pre-0.8.0 semantics, written into the one file
  the tool creates in a user's repository. A user uncommenting the line as shown
  would have turned the ranking **on** believing they were accepting a default.
  The scaffold now shows `enabled = false`, states that uncommenting turns it on,
  and points at the caveat.

- **Three pairs of series colours were indistinguishable in normal vision.**
  The eight-slot palette was replaced in this release with a "measured" one,
  and it had not been measured against every pair. Recomputing all 28 pairs in
  OKLab found 13 below target — and not only for colour-blind readers: orange
  against red measured 7.1 in ordinary vision, magenta against red 7.8, blue
  against violet 9.8. Two contributors drawn in colours nobody can separate is
  a chart stating something false.

  A series colour here has to clear three constraints at once, because one
  fixed set is drawn on both themes: 3:1 against each plot surface, 15 OKLab
  units from every other slot in normal vision, and 6 units under simulated
  protanopia, deuteranopia and tritanopia. Searched over 29 candidates, **the
  largest set satisfying all three is four.** The palette is now those four —
  Okabe & Ito's Color Universal Design hues where they clear the dual-surface
  requirement — and both `_MAX_SERIES` and `_PIE_MAX_SLICES` derive from its
  length, so a fifth contributor aggregates rather than borrowing a hue.

  `tests/unit/adapters/test_palette.py` carries the arithmetic and recomputes
  all of it on every run, including two tests that check the colour-blindness
  simulation still narrows a known red/green pair — a CVD check that cannot
  see a confusable pair proves nothing. It immediately found a second defect:
  the neutral used for the residual pie slice and the Lorenz reference line
  now sat close to three of the new hues, so the aggregate would have read as
  a person. It is a true neutral of zero chroma, which is the property that
  actually separates scaffolding from identity.

- **Axis titles were drawn over the tick labels, and contributor names were
  cut off.** Every chart used a fixed 50px bottom and 60px left margin. That
  is a guess, and it was wrong in both directions: the weekly timeline's
  `-45°` date labels ran under the word "Week", and the contributor bar chart
  truncated names to `dabot[bot]` and `Chilakanti`. Both axes now set
  `automargin`, so Plotly measures what it has drawn and reserves the space
  it needs.

- **The Gini coefficient sat where the legend sits.** It was the Lorenz
  chart's own title, anchored top-left; Plotly anchors the legend there too,
  and the two overlapped in every export. It is now a figure on the section
  heading. The test that held it to the domain calculation was repointed
  rather than dropped, and a new one fails if it is put back inside the plot.

- **The distribution caption was a two-paragraph essay above the chart.** A
  reader looking for the finding had to read past the method to reach it. The
  lead is now one sentence; the caveat — that this describes the repository
  and not the people in it — is a short footnote under the chart, where a
  reader who is questioning the finding will look for it. Printing rules were
  added at the same time, so a chart or table is no longer split across a PDF
  page break.

- **This repository had no `.mailmap`, and its own report showed it.** One
  commit made through the GitHub web interface carried the account's noreply
  address, so the contributors table listed three people where there are two.
  The spare row was the smaller problem: the charts key on the display name,
  and Plotly resolves a repeated label differently per trace type — a bar
  chart collapses the bars onto one category, a pie sums the slices. The
  table read 201 and 1, the bar chart read 201, and the pie read 202. Three
  views of one repository, three answers. A `.mailmap` now maps the
  identities; all three agree at 202, and the User Guide points at the file
  as the worked example of the case that produces it. `git shortlog` and
  GitHub's contributors graph agree too, which needed the prefixed noreply
  address mapped literally — Reveille strips the numeric prefix before
  resolving, and they do not.

- **The User Guide still promised what ADR 0010 refuses.** Its identity
  section said a `.mailmap` ensures "ranking and contribution metrics reflect
  actual individual output". The generated scaffold was corrected earlier in
  this release and the prose it was copied from was not. It now says what
  `.mailmap` does: one person committing under several addresses is counted
  once rather than once per address.

- **The generated `.mailmap` made the claim this release exists to retract.** Its
  header said mappings ensure *"rankings reflect actual individual output"* —
  exactly the reading ADR 0010, `reveille capabilities` and the DORA/SPACE
  citation all refuse. It now says what `.mailmap` actually does: one person
  committing under several addresses is counted once.

- **The CLA check could never pass with the pull-request template this repository
  ships.** The acceptance pattern required the tick and the `Reveille-CLA-1.0`
  token on the same physical line, while the template wraps that bullet across
  three. Every external contribution would have failed the gate, and the failure
  message told the contributor to tick a box they had already ticked. The check
  now scopes to a single markdown list item — the ticked line plus its indented
  continuations — so it accepts the wrapped form while still rejecting a ticked
  "I ran the tests" box that merely has the token somewhere else in the body.
  `tests/unit/test_cla_gate.py` runs the shipped script against the shipped
  template, so the two cannot drift apart again.

- **`GitReader.unmatched_exclusions` never cleared.** It was assigned only when
  non-empty, so a reader reused for a second call still reported the first call's
  failed `--exclude-author` filter — a warning about a filter the caller had not
  asked for. It is now cleared on entry and assigned unconditionally.

- **`actionlint` was configured but never enforced.** It ran as a pre-commit hook,
  and `make precommit` was referenced by no workflow, so the cited
  workflow-correctness guard only ever ran for developers who had installed the
  git hooks locally. CI now runs it as a `Workflow correctness` job.

- **The workflow-pin guard globbed `*.yml` only.** A `.yaml` workflow — which
  GitHub honours identically — would have been entirely unchecked for SHA pinning,
  and the discovery test counts pins rather than files, so it would not have
  noticed. Verified by dropping an unpinned action into a `.yaml` file and
  watching the guard fail.

- **Pre-commit hooks were pinned to mutable tags** while `test_workflow_pins.py`
  requires SHA pins for GitHub Actions on the grounds that a movable tag is an
  arbitrary-code seam. A pre-commit hook executes on every developer commit and is
  the same seam, so both third-party hooks are now pinned by commit.

- **A screen-reader accessibility test asserted a magic number.** It required at
  least ten `scope="col"` attributes — the ranked table's column count — so
  removing three columns for the ranking opt-in failed it with nothing wrong. It
  now asserts the property it was proxying for: that no column header lacks a
  scope, whichever columns are present.

- **The offline-guarantee test named three tags, and the guarantee has more than
  three ways to lose.** It rejected a remote `<link href>`, `<script src>` and
  `<img src>`. An `<iframe src>`, an `<object data>`, a `<video poster>`, a CSS
  `@import` and a CSS `url()` each forfeit the offline guarantee, and all five
  were confirmed to pass that test with the violation present. The property is
  now asserted instead: nothing the browser fetches — in markup or in the inline
  stylesheet — may name a remote host. `<script>` bodies stay excluded, because
  the vendored Plotly bundle carries map-tile attribution URLs as string
  literals for trace types Reveille never emits; `<style>` bodies are not
  excluded, because a stylesheet is applied. `<a href>` is deliberately still
  allowed: it navigates on a click and loads nothing, and flagging it would make
  the guard cry wolf. All seven violations were observed failing the new test,
  and a remote `<a href>` was confirmed not to trip it.

- **Chart area fills were hardcoded `rgba(...)` literals** that happened to equal
  `_CATEGORICAL_PALETTE[0]`. Nothing coupled them, and the palette was replaced
  wholesale in this release — a further change would have left a fill in the old
  hue beneath a line in the new one. Both now derive from the palette entry.

- **`llms.txt` reintroduced an overclaim** that `capabilities.py` had been
  corrected to remove: *"The only file written is the output path you name."*
  `reveille init` writes `reveille.toml` and `.mailmap`. Same machine audience,
  same correction.

- **The Lorenz curve — the chart that replaces the ranking in the default report —
  shipped with no test at all.** Mutation testing confirmed it could be deleted
  from the report entirely, have its Gini figure doubled, or fill the wrong region,
  with the whole suite still passing; the ranking it replaces has thirty-odd tests.
  `tests/unit/adapters/test_lorenz_chart.py` adds twenty-five, covering geometry,
  the Gini title, colour coupling, degenerate inputs, and — the mutation the first
  draft of those tests missed — that the chart actually reaches the rendered report.

- **`poetry.lock` was not valid TOML, and CI failed on seven consecutive merges to
  `main`.** A merge conflict inside plotly's `[package.extras]` table was resolved by
  removing the conflict markers and keeping both sides, which duplicated four keys
  (`dev`, `dev-build`, `dev-core`, `dev-optional`). Duplicate keys are a TOML syntax
  error, so `poetry install` failed outright and every `lint`, `typecheck` and `test`
  job stopped before running anything — reporting "Unable to read the lock file",
  which names the symptom rather than the cause. The lock was regenerated: every
  runtime dependency resolves to exactly the version it did before, and six
  development tools moved — `coverage` and `python-discovery` by a minor release,
  `filelock`, `platformdirs`, `ruff` and `virtualenv` by a patch.

- **The chart palette was replaced with a measured one.** The previous set put
  `#22c55e` next to `#14b8a6` at a normal-vision perceptual distance of ΔE 11.3 —
  below the 15 floor at which two adjacent series stop being reliably separable by a
  reader with full colour vision — and they were adjacent, so the second- and
  third-ranked contributors were the pair that collided. The replacement was
  validated against both report surfaces before adoption: worst adjacent pair is
  ΔE 19.3 normal vision and 8.4 under protanopia, clearing both floors in each mode.
  One palette now serves both themes, so no colour changes when the theme is toggled.

- **The activity heatmap read backwards in dark mode.** Its colour ramp was fixed
  across themes and ended at a near-black blue: 9.73:1 against the light plot
  background but **1.67:1 against the dark one**. The busiest days faded into the
  background while the quietest glowed — the encoding inverted exactly where the
  data mattered most. There are now two single-hue ramps, one per theme, each
  checked so contrast against its own surface rises at every step. The theme toggle
  re-renders the heatmap rather than relayouting it, because a colorscale lives on
  the trace and `Plotly.relayout` does not touch it.

- **Two charts could draw two different contributors identically.** The
  contributor timeline drew one trace per contributor with `palette[i % len]`, so
  the ninth contributor silently reused the first one's colour and line style; it
  now caps at the palette length, and everyone else remains in the rankings table
  and the heatmap's contributor filter, neither of which has a colour budget. The
  commit-share pie aggregated past eight slices but then requested nine colours
  from an eight-colour palette, so "Other Contributors" wrapped around and shared a
  colour with the top-ranked contributor **inside the same chart**; the residual
  slice now takes a reserved neutral, which is also what it means.

- **`make check-version` and `make check-licence` could pass while checking nothing.**
  Both read their two values through `poetry`, and both compared the results without
  first asserting either was non-empty. If `poetry` failed for any reason, both
  variables became empty strings, `"" != ""` was false, and the guard reported
  agreement and exited 0 — with `__licence__` set to anything at all. Both now fail
  closed and refuse to compare two blanks.

- **`--since` silently dropped commits inside the window.** Git's `--since` is
  *greedy*: the walk stops at the first commit older than the boundary and does
  not resume, so anything further down the parent chain is never examined — even
  when it is squarely inside the range. Measured on a three-commit chain dated
  01-15, 01-01, 01-20 with `--since 2024-01-08`: one commit returned, the 01-20
  one silently lost. Rebases, cherry-picks, merged old branches and ordinary clock
  skew all produce that shape. Now uses `--since-as-filter`, probed for support
  since it needs git 2.37.

- **A malformed `[ranking] weights` printed a traceback and exited 1.** Both
  `float()` and the `RankingWeights` model could raise past the handler, so
  weights that were non-numeric or did not sum to one crashed rather than
  reporting. Exit 1 means "ran correctly, negative answer" on the published
  contract, so a CI job would have read a crash as a clean result.

- **A per-contributor chart had no height limit.** 5,000 contributors produced a
  bar chart 220,080 pixels tall, which no browser renders usefully. Capped.

- **`[report] format` in `reveille.toml` was silently ignored.** The CLI assigned
  `output_format` unconditionally, and the flag's default was `"html"` — so the
  default overwrote whatever the config file said. A user automating a JSON export
  via config got HTML, exit 0, no warning. This is the same defect the `min_commits`
  `None` sentinel was introduced to fix; the fix had never been applied here.
  Verified in all three directions: config-only now yields JSON, an explicit flag
  overrides the config, and no config still defaults to HTML.

- **`--since` and `--until` meant different things on different machines.** Git
  parses a bare `YYYY-MM-DD` in the *local* timezone, while every timestamp
  Reveille renders is UTC. Measured with one commit at `2024-06-10T22:00Z` and
  `--since 2024-06-11`: empty under UTC, empty under `America/Los_Angeles`, a full
  report under `Pacific/Auckland` — same repository, same flags, three different
  answers. Window boundaries are now pinned to UTC, which is also what
  `--deterministic` needs in order to mean anything.

- **Three guards passed while checking nothing**, found by re-breaking every
  invariant rather than by reading:

  - `tests/unit/test_architecture.py` exempted every `__init__.py`, which blinded
    the offline guarantee, the dependency-direction rule and the filesystem-write
    rule *simultaneously* — in the one file guaranteed to execute on import.
  - The offline-moat test matched only double-quoted attributes, so
    `<link href='https://…'>` passed. A sibling check three hundred lines away had
    it right.
  - A security assertion was a disjunction already true on its right operand.

- **`reveille capabilities` failed open.** It read the command list with
  `getattr(group, "commands", {})`, so a Click internals change would have emitted
  a valid-looking document claiming the tool has no commands, exit 0, to a program
  that trusts it. It now refuses. Its test compared `set(X) == set(X)` and would
  have passed with both sides empty; it now also checks an independent literal.

- **The README had lost its licence section and grown a duplicate heading.** An
  edit during this release truncated the file at `## Licence`, so the licence
  section disappeared, `## Contributing` appeared twice, and the table of contents
  pointed at a heading that no longer existed. Every individual link still
  resolved, so nothing failed — the document was internally broken in a way only
  its own structure revealed. Repaired, and two guards added: no `##` heading may
  appear twice, and the contents list must match the headings exactly.

- **`deterministic` was a CLI flag with no `reveille.toml` key.** The field existed
  on the configuration model and the documentation describes `reveille.toml` as
  the single configuration surface, but the parser never read it, so
  `[report] deterministic = true` silently did nothing. Found by the new
  configuration-surface fitness function on its first run, not by review — every
  individual piece worked, which is why nothing else noticed.

- **An author name had no length limit, and one field could exhaust memory.**
  Git imposes no bound, and the field is attacker-controlled under this project's
  threat model. Measured: a single commit with a 100,000-character name turned a
  four-commit repository into a 6.5 MB report; a 1,000,000-character name reached
  1.5 GB of resident memory. The name is repeated in the contributor table, two
  bar charts, every tooltip, the heatmap contributor list, and the JSON and CSV,
  so its cost is multiplied several times over. Names are capped at 256
  characters and addresses at the RFC 5321 limit of 320, with the truncation
  marked. The same repository now produces a 4.3 MB report.

- **`--exclude-author` did not remove a person with a `.mailmap`.** It matched
  only the literal value, so excluding somebody's old address dropped the commits
  authored under it and left them in the report under their canonical identity —
  exit 0, no diagnostic. For the one flag whose stated purpose is privacy, that is
  the wrong direction to be approximate in. An exclusion now expands through the
  `.mailmap` to every identity it ties the value to. The one case that cannot be
  resolved is a display *name* that only ever appeared before the mailmap, because
  a two-field mailmap records the old address and never the old name — the
  documentation now says exactly that instead of claiming more.

- **A warning that mattered was only visible with `--verbose`.** An exclusion
  matching nothing is almost always a typo, and silence made it indistinguishable
  from a filter that worked. A stderr handler is now attached on every run at
  WARNING level; `--verbose` still lowers it to DEBUG, and importing Reveille as a
  library still installs no handler at all.

- **An explicit `--config` was treated as untrusted.** The output-path boundary
  added earlier this release could not tell an auto-discovered `reveille.toml`
  from one the user named, so `--config /my/file.toml` was refused and told the
  user their file had been "discovered automatically", which was false. Only
  auto-discovery is untrusted now.

### Security

An adversarial review found five issues, each reproduced against a real
malicious repository before being fixed. The threat model throughout is that
**a victim runs Reveille against a repository somebody else controls** — a
clone, a fork, a pull-request branch. Everything in git history is then
attacker-supplied text, and so is any `reveille.toml` at the repository root,
because the CLI discovers that file automatically from the working directory.

- **Argument injection into `git log`, allowing arbitrary file overwrite.** A
  revision beginning with `-` is parsed by git as an option, and the trailing
  `--` separates revisions from *paths* — it does not protect the revision
  slot. `--branch "--output=/path/to/file"` made git write its log output over
  that file. Reachable with no flags at all through an auto-discovered
  `reveille.toml`, so running `reveille generate` inside a clone was enough.
  Revisions beginning with `-` are now refused, and `--end-of-options` is
  passed as a second line of defence.

- **CSV formula injection.** Contributor names are written to a CSV opened with
  a BOM specifically so Excel reads it directly, and nothing neutralised a
  leading `=`, `+`, `-`, `@`, tab or carriage return — the route to `HYPERLINK`
  exfiltration and, historically, DDE command execution. Free-text cells are
  now prefixed with an apostrophe when they would otherwise be evaluated.
  Numeric columns are untouched, so a real minus sign still reads as one.

- **Contributor forgery through separator injection.** The single-pass reader
  splits `git log` output on ASCII 0x1E and 0x1F. Git's ident sanitiser strips
  `<`, `>` and newlines from an author field but **not** other control
  characters, so a commit object written with `git hash-object --literally`
  could inject a whole extra record and fabricate a contributor — who the
  ranking would then promote into a tier. Records are now accepted only if
  their object name appears in a list `git rev-list` produced, where the
  attacker has no say. Scrubbing the fields afterwards cannot fix this and was
  not enough on its own: by the time a field is scrubbed, the split has already
  happened.

- **Output path validation ran on the wrong path, and writes followed symbolic
  links.** The CLI validated the `--output` flag but wrote the merged value, so
  a path supplied by a configuration file skipped the traversal check
  entirely. Separately, `write_text` follows a symlink, so an output path
  pointing at one overwrote its target. Both are fixed; the symlink check runs
  before the path is resolved, because `Path.resolve()` follows the link and
  makes the check pass every time.

- **A forged timestamp crashed the run.** A commit carrying a non-numeric or
  out-of-range `%ct` raised an unhandled `OverflowError`. That record is now
  skipped and the report still generates.

**Verified unaffected**, and worth stating because they were tested rather than
assumed: HTML and JavaScript injection into the report (Jinja2 autoescaping is
on and chart JSON is escaped at the `</` sequence, so payloads stay inert
text); the offline guarantee (zero remote-loading tags; the only network code
in the vendored Plotly bundle is map-tile handling that is unreachable because
no map trace is ever constructed); the `.mailmap` parser (all patterns linear,
no ReDoS); and the CI workflows (no `pull_request_target`, no untrusted
interpolation into `run:` steps).

- **A second adversarial review found three more, plus five smaller issues.**
  The first pass had fixed a symlink check that ran on the **final path
  component only** — and a symlinked *parent directory* is not a symlink at the
  leaf, so the guard passed while a 4 MB report landed outside the repository.
  Git stores symlinks, so a hostile repository can commit one; the victim clones
  and runs bare `reveille generate`, and an auto-discovered `reveille.toml`
  chooses the destination. An output path supplied by a configuration file is now
  a hard error if it resolves outside the repository. An explicit `--output` is
  unaffected, because a path the user typed may legitimately point anywhere.

- **`reveille init` had no symlink guard at all**, and `.mailmap` is a Git-native
  file a repository can commit *as a symlink*. A dangling link also passed the
  `exists()` check, so no `--force` was needed. Both writers now refuse.

- **A configuration reading `enabled = "false"` switched the ranking ON.** The
  parser used `bool(...)`, and every non-empty string is truthy. Given that the
  ranking is the one feature that names individuals, that was the wrong direction
  to fail in. Non-boolean values are now rejected outright.

- **`--exclude-author` republished the excluded person's address.** The one
  operation whose purpose is to keep somebody out of the report wrote their email
  into a labelled `provenance.filters.exclude_authors` field — promoting it from
  one row among many to something greppable. Provenance now records
  `exclude_authors_count`, which still distinguishes a filtered report from an
  unfiltered one without republishing anybody.

- **`--exclude-author <name>` silently missed anyone renamed by a `.mailmap`.**
  `git log --format=%an` shows the *pre*-mailmap name, so that is what a user
  copies — and only the resolved name was matched. The person stayed in the
  report, fully identified, exit code 0, no diagnostic. Both raw and resolved
  identities are matched now, and a filter that matches nothing is reported
  rather than passing in silence.

- **A malformed `reveille.toml` printed a traceback and exited 1.** `int()` and
  `list()` were called bare, so a mistyped value raised outside the handler.
  Exit 1 means "ran correctly, negative answer" on this project's published
  contract; a CI job branching on it would read a crash as a clean result. Each
  parser now raises a typed error naming the offending key, and exits 2.

- **The capability document overstated two guarantees.** It claimed the analysed
  repository is never modified and that the only file written is the report you
  name — both false for `reveille init`. Corrected, because the whole point of
  that document is that a program can trust it.

- **The CLA acceptance check matched a tick on an unrelated line.** The pattern
  was unanchored with `re.DOTALL`, so any ticked box followed anywhere by the
  agreement string counted — including one inside a code fence. It is now scoped
  to a single markdown list item. The first attempt anchored to a single physical
  line, which could never match the wrapped template this repository ships; see
  *Fixed*, above.

- **31 security regression tests.** Each was observed failing against the
  reintroduced vulnerability. One of them did not, on first writing: the
  forgery payload was rejected by an unrelated field-count check rather than by
  the guard under test, so it proved nothing. It was rebuilt until removing the
  guard genuinely failed it.

## [0.7.0] — 2026-08-06

### Added

- **The ranking weights are now justified rather than merely stated.** The defaults
  (30/25/25/20) appeared in the README, the User Guide, and two docstrings with no
  recorded reasoning anywhere in the codebase — the one part of Reveille most likely to be
  questioned was the one part that could not answer. They are now documented as a
  judgement rather than a derived model, with the reasoning for their relative ordering:
  commits weighted highest for robustness, lines lower because a lockfile or reformatting
  pass distorts them, recency lowest because recency is a property of the analysis window
  rather than of the person.

- **Documentation of what the ranking does not measure.** The README, the User Guide, and
  `domain/ranking.py` now state plainly that the ranking measures volume and regularity of
  commits — not contribution, productivity, or value — and that it must not be used to
  assess individuals, which is the explicit position of both DORA and SPACE. The military
  tier designations are described as a visual device, not a rank, and `--no-ranking` is
  documented as the way to drop scores while keeping every other section of the report.

- **`llms.txt`** — a short index pointing a coding assistant at the right document, plus
  the handful of facts about Reveille that are easy to get wrong: that it never writes to
  a repository, that merge commits are excluded so its counts are lower than `git log`,
  that commit concentration is not a bus factor, and that the ranking must not be used to
  assess individuals. It is a proposed convention, not a standard, and nothing depends
  on it.

- **The link test now checks absolute self-referential URLs.** The README and `llms.txt`
  link to their own repository by full URL so they render correctly on PyPI, which the
  relative-path check could not see; 17 such links are now verified to point at files that
  exist.

- **`docs/ARCHITECTURE.md` documents how Reveille is built.** The architecture record
  previously existed only in a gitignored working file, so a contributor cloning the
  repository could not read the layering contract they were expected to honour. It covers
  the dependency rule and framework ownership, the domain model, the error model and exit
  codes, the analysis pipeline, identity resolution, ranking, and the invariants the test
  suite exists to protect. It was rewritten against the source rather than copied: the
  prior record was pinned at v0.5.0 and predated the exception rename, JSON and CSV
  export, `ProgressEvent`, exit codes, the single-pass history read, and the commit
  concentration rename.

- **`docs/adr/` records six decisions with their reasoning** — unconditional merge-commit
  exclusion, email as the identity key, lower-bound percentile ranking, the single-pass
  `--numstat` read, commit concentration over "bus factor", and the offline single-file
  report. Each states what the decision costs and what it rules out, so a future reversal
  argues with the original reasoning rather than reconstructing it.

- **A layering test enforces the dependency rule.** `tests/unit/test_layering.py` imports
  each layer in a clean interpreter and asserts which frameworks reach `sys.modules`. A
  contract that lives only in a document erodes one convenient import at a time with
  nothing failing; this one fails the suite.

- **A documentation link test** asserts that every relative link between repository
  documents resolves, and that no ADR is missing from its index. Cross-references rot
  silently — a renamed file leaves a link that still reads correctly and 404s.

- **`.gitattributes`, `.editorconfig`, `.github/CODEOWNERS`, and `CODE_OF_CONDUCT.md`.**
  The consequential one is `* text=auto eol=lf`: without it, checkouts on different
  platforms produce different bytes for the same commit and cross-platform contributors
  generate whole-file diffs that bury the actual change. No tracked file currently
  contains CRLF, so adding it produces no renormalisation diff. `.editorconfig` is
  deliberately narrow and defers all formatting to ruff rather than restating it.

- **Every tagged release now generates a CycloneDX 1.6 SBOM.** The bill of materials
  covers the runtime dependency graph resolved from `poetry.lock`; development and test
  dependencies are excluded, because they describe how Reveille is built rather than what
  an installation of it contains. It is uploaded as the `sbom` workflow artifact and
  attached to the GitHub Release. Generation runs in a job that is independent of
  publishing in both directions, so a failure to produce an SBOM cannot withhold a
  release. The same file can be regenerated from any checkout with `make sbom`, and the
  output is byte-reproducible for a given lock file, so a regenerated SBOM can be compared
  directly against a published one. The generator is deliberately not a project
  dependency — it reads `pyproject.toml` and `poetry.lock` as files, so the tool that
  describes the dependency graph is not a member of it.

- **`SECURITY.md` now documents how to verify a downloaded distribution.** Reveille has
  been publishing [PEP 740](https://peps.python.org/pep-0740/) attestations since the
  release workflow was written — `pypa/gh-action-pypi-publish` produces them by default
  from v1.11.0 onward, this repository pins v1.14.1, and the required `id-token: write`
  permission was already granted — but nothing said so, and an unstated guarantee is not
  one a consumer can act on. The policy now records the trusted-publisher setup, the exact
  `pypi-attestations verify pypi` invocation, and the caveat that the CLI describes itself
  as experimental even though the attestation format is a standard.

- **A test asserts every GitHub Action is pinned to an immutable commit SHA** and that its
  trailing comment names a precise version. An action referenced by a mutable tag executes
  whatever that tag points at on the day the workflow runs, which is an arbitrary-code
  seam in the release path.

- **Two tests hold the CLI reference to the CLI.** One asserts `reveille version` fails.
  The other compares the commands named in the README's CLI Reference against the commands
  Typer actually registered, in both directions — a documented command that does not
  exist, and a real command the README omits. The commands are read from the Typer group
  rather than parsed out of `--help` text: a first attempt did parse the help output and
  passed while the README documented a nonexistent command, because the name matched
  inside an option's description sentence.

- **The HTML report is now navigable with assistive technology.** It previously carried
  no ARIA attributes, no table header scopes, and no text alternatives, which matters
  because the report is explicitly built for stakeholder distribution — Confluence
  embedding and email — the context in which WCAG 2.1 AA and EN 301 549 are asked about.
  Specifically: every contributor-table column declares `scope="col"` and each rank cell
  is a `scope="row"` header, so a screen reader announces which column a figure belongs
  to; the table carries a caption naming the repository and analysis window; each of the
  seven Plotly charts is exposed as a single labelled image with a described text
  alternative, since SVG conveys nothing to a screen reader, and the alternatives point
  at the contributor table that carries the same figures; the heatmap contributor filter
  and year selector have accessible names, where the filter previously had none at all;
  the year buttons expose their selected state through `aria-pressed`; summary cards
  present the label and value as one phrase rather than two orphaned elements; the report
  body is a `<main>` landmark; and `prefers-reduced-motion` is honoured per WCAG 2.1
  SC 2.3.3.

- The offline guarantee is now asserted in the test suite: no `<link>`, `<script>`, or
  `<img>` in the rendered report may reference a remote host.

- **Exit codes now distinguish a negative answer from an inability to run.** Every
  command returns `0` (success), `1` (Reveille ran and the repository state does not
  satisfy the request — an empty analysis window, or a repository with no commits), or
  `2` (Reveille could not run — invalid flag value, malformed configuration, a path that
  is not a readable Git repository, or an unwritable output location). Previously every
  failure returned `1`, so a CI job could not tell "this repository has nothing to report
  yet", which may be acceptable, from "this step is misconfigured", which is not. The
  codes are documented in the User Guide and are a supported contract. **Anyone currently
  branching on a non-zero exit should note that configuration and repository-access
  failures now return `2` rather than `1`.**

- `--verbose` on `generate` and `validate` writes DEBUG-level diagnostics to stderr: the
  fully resolved configuration after CLI flags and TOML have been merged, the exact
  `git log` invocation, the commit count read, and every file written. Normal output is
  unchanged, so the flag is safe to add to an existing pipeline. Reveille's modules log
  through the standard `logging` module under the `reveille` logger and install only a
  `NullHandler`, so importing Reveille as a library remains silent unless the host
  application configures logging itself.

- Python 3.13 and 3.14 are now supported and tested. The CI matrix runs the full suite on
  3.11, 3.12, 3.13, and 3.14, and both new versions appear in the PyPI classifiers.
  Previously the `^3.11` constraint permitted installation on 3.13 and 3.14 while CI
  tested only 3.11 and 3.12 and the classifiers advertised only those two — users on newer
  interpreters were running an untested, unadvertised configuration. `CONTRIBUTING.md`
  now states the support policy: every non-EOL CPython at or above the 3.11 floor, added
  to the classifiers only once CI proves it, dropped on upstream EOL, and never
  upper-capped below 4.0.

- The CI test matrix sets `fail-fast: false`, so a failure on one interpreter no longer
  cancels the others.

- Complete `.mailmap` support. All four forms documented in gitmailmap(5) are
  now parsed, where previously two were. The four-field form
  (`Proper Name <proper@email> Commit Name <commit@email>`) matches on commit
  name and email together, which is the only form that can disentangle several
  people who committed under one shared address — a default `git config` left
  in place on a build machine, for example. Where more than one entry could
  apply, the most specific wins, matching Git. A comment now runs to the end of
  the line rather than requiring its own line, and names and addresses are
  matched case-insensitively, both as Git does. Verified against
  `git log --use-mailmap`: identical resolved identities across every form.

- `reveille init --mailmap` documents the two previously undocumented forms
  with worked examples, and no longer states that the four-field form is
  unsupported.

### Changed

- **The User Guide documents the single-pass history read.** The pipeline walkthrough now
  states the measured cost (~0.8 ms per commit, so a 50,000-commit history reads in under
  a minute) and states explicitly that Reveille never writes to the repository — no
  commits, no branches, no configuration changes, no mutating Git command.

- **Two module docstrings predated JSON and CSV export.** `services/report.py` described
  step 7 as rendering HTML, and `adapters/renderer.py` called itself the "HTML report
  renderer". Both now describe the three-format dispatch.

- **`CONTRIBUTING.md` no longer claims the domain layer has no framework imports.** It
  does have one: `domain/ranking.py` imports `RankingWeights` from `config.py`, which is a
  Pydantic model. This is a deliberate trade — the alternative is two definitions of the
  same four weights that can drift — but the document stated the stronger claim, and a
  contributor checking it against the source would have found the document wrong. The rule
  is now stated as what it actually protects: the domain performs no I/O and no rendering.
  `tests/unit/test_layering.py` enforces that version.

- **Action pin comments now name exact versions.** Four pins were labelled with moving
  aliases — `# release/v1` on `pypa/gh-action-pypi-publish`, `# v1` on
  `snok/install-poetry`, `# v6` on `codecov/codecov-action`, and `# v4` on
  `github/codeql-action` — which told a reviewer nothing about whether the pin was
  current. They now read `# v1.14.1`, `# v1.4.2`, `# v6.0.2`, and `# v4.37.3`. The pinned
  SHAs themselves are unchanged; only the comments were wrong.

- The base exception is now spelled `ReveilleError`. It had been `RevelleError` —
  missing the second `i` — since the first release, and as the documented catch-all for
  library consumers the typo sat directly on the public API surface. **No consumer code
  needs to change**: `RevelleError` remains importable as a deprecated alias resolving to
  the same class, so `except RevelleError` continues to catch every Reveille failure.
  Accessing it emits a `DeprecationWarning` naming the replacement and the removal
  version. The alias is removed in **v1.0.0**, where the public API becomes stable —
  correcting it now is the last opportunity to do so at no cost to users.

- `reveille.exceptions` now declares `__all__`, and its module docstring carries the full
  exception hierarchy.

- **Breaking (JSON output):** the derived metric previously reported as
  `bus_factor` is now `commit_concentration`. The computation is unchanged —
  the minimum number of contributors whose combined commit volume reaches 50
  percent of the total — but the old name claimed something the number does
  not measure. Bus factor is knowledge concentration: how much of the
  surviving code only one person understands. That is a property of line
  ownership, answerable only by `git blame` across every file, and commit
  counts are a weak proxy for it — a contributor making many small commits
  outranks one who wrote a subsystem in a few large ones, and work since
  rewritten still counts in full. The HTML summary card is relabelled
  "Commit Concentration" and the User Guide explains what the number does and
  does not support. Consumers reading the JSON `derived.bus_factor` key must
  update to `derived.commit_concentration`.

- Commit history is now read in a single `git log --numstat` subprocess,
  including per-commit line counts. The previous implementation obtained line
  counts through GitPython's `Commit.stats`, which spawns one `git diff` per
  commit and dominated runtime on any repository large enough to matter.
  Measured on Reveille's own repository, the read path drops from 7.2 ms to
  0.77 ms per commit — a 9.4x improvement that takes a 50,000-commit
  repository from roughly six minutes to under a minute. Output is unchanged:
  every commit, line count, timestamp, and resolved identity is identical to
  the previous implementation, including the treatment of binary files (zero
  lines), commits that changed no files (zero lines), and root commits
  (diffed against the empty tree). No configuration, flag, or API change.

### Fixed

- **`pip install reveille` printed a warning on every install.** The Typer dependency was
  declared as `typer[all]`, and Typer declares no extras at any version in the supported
  range, so pip emitted `WARNING: typer 0.27.1 does not provide the extra 'all'` — the
  first thing a new user saw. The extra was never load-bearing: `rich` and `shellingham`,
  what it used to pull, are ordinary dependencies of `typer` itself, and `typer-slim` is
  the variant that omits them. Verified at both ends of the range (0.18.0 and 0.27.1):
  neither declares an extra, and both install `rich` and `shellingham` regardless. The
  resolved dependency set is byte-identical — only the lock file's content hash changed.

- **The README documented a `reveille version` command that does not exist.** The version
  string is exposed as a global `--version` / `-v` flag; there is no `version` subcommand,
  so anyone copying the invocation out of the CLI reference got
  `No such command 'version'`. Found by running it rather than by reading it — every
  documentation guard in this release compares text to text, which is why it survived them
  all.

- **The User Guide claimed the four-field `.mailmap` form was unsupported.** It has been
  supported since the mailmap work landed earlier in this release, so the guide was
  telling users a capability they had did not exist. The claim appeared in two places —
  the identity-resolution walkthrough and the `reveille init --mailmap` reference, where
  the form was described as "marked as unsupported by Reveille in this release". Both now
  describe all four `gitmailmap(5)` forms, the most-specific-match precedence Reveille
  follows, case-insensitive matching, and the automatic folding of GitHub noreply
  addresses.

- **`CONTRIBUTING.md` claimed CI runs across Python 3.11 and 3.12.** The matrix has
  covered 3.11 through 3.14 since the support-policy change earlier in this release. It
  now refers to the support policy rather than restating a version list that will drift
  again.

- **A `RankingWeights` docstring contradicted its own code**, documenting a `1e-9`
  tolerance where the validator uses `1e-6`.

- **The muted text colour failed WCAG 2.1 AA contrast in both themes.** Light theme
  measured 3.04:1 against the page background and 2.85:1 against raised surfaces — the
  latter below even the 3:1 large-text threshold — and dark theme measured 4.12:1 and
  3.77:1, against a 4.5:1 requirement for normal text. Both tokens are corrected
  (`#8c959f` → `#69717a` light, `#6e7681` → `#7d8590` dark) and now clear AA on every
  surface while remaining visibly lighter than secondary text, so the visual hierarchy is
  unchanged. Contrast is now computed from the template's own CSS custom properties in
  the test suite rather than checked by eye, so a future palette edit cannot silently
  reintroduce the regression.

- A readable repository containing no commits at all now raises `EmptyRepositoryError`
  rather than `RepositoryError`. It had surfaced as a repository-access failure because
  `git log` errors on an unborn HEAD, which conflated "this repository is unreadable"
  with "this repository is empty" — the two states the new exit codes exist to separate.

- Reveille now ships the PEP 561 `py.typed` marker. The package has advertised the
  `Typing :: Typed` classifier since v0.5.0 while the marker was absent from every
  built distribution, so type checkers in downstream projects reported Reveille as
  missing library stubs and ignored its annotations entirely — the `mypy --strict`
  guarantee applied inside the project but delivered nothing to consumers of it.
  Installing this release makes Reveille's inline types visible to `mypy`, `pyright`,
  and any other PEP 561-aware checker with no change required on the consumer side.

- `make check-packaging` asserts the marker survives into both the wheel and the sdist,
  and runs in CI alongside the existing version-sync check. The defect persisted because
  nothing verified it; a claim the build does not check is a claim that silently stops
  being true.

- The email-only `.mailmap` form (`<proper@email> <commit@email>`) was parsed
  as a name-only entry, taking the literal text `<proper@email>` — angle
  brackets included — as the contributor's display name and leaving the address
  unmapped. It now replaces the address and preserves each commit's own name,
  which is what Git does.

- GitHub's two private-commit address forms are now folded together. An account
  whose history spans GitHub's 2017 change appears under both
  `username@users.noreply.github.com` and
  `12345678+username@users.noreply.github.com`, and aggregated as two separate
  contributors. The numeric account ID is stripped, so both forms resolve to one
  identity, and the ID no longer leaks into report output. A `.mailmap` entry is
  an explicit statement of intent and always takes precedence over this
  automatic folding; entries written against either form are honoured, the
  address as recorded on the commit taking priority. `--exclude-author` matches
  the raw address as well as the resolved one, so a value copied from `git log`
  continues to work.

- Note the scope of this fix: it merges an account's *noreply* addresses with
  each other. It cannot merge a noreply address with a personal address, since
  nothing in the commit data establishes that link. A contributor who commits
  both locally and through the GitHub web interface still needs a `.mailmap`
  entry to appear once; `reveille init --mailmap` generates an annotated
  template covering exactly this case.

---
## [0.6.0] — 2026-05-29

### Added

- `reveille init --mailmap` generates an annotated `.mailmap` template at the
  repository root alongside `reveille.toml` in a single invocation. The template
  documents the two-field form (name correction), three-field form (email alias
  to canonical identity), and four-field form (name and email alias, marked as
  unsupported by Reveille in this release), each with concrete real-world examples
  covering employer domain changes, GitHub noreply addresses, and name corrections.
  `--force` applies to both generated files. An existing `.mailmap` is silently
  skipped without error; `.mailmap` is a Git-native file and its presence is not
  treated as a conflict.
- `ProgressEvent` frozen dataclass introduced in `reveille.domain.models`.
  The pipeline progress callback signature changes from `Callable[[str], None]`
  to `Callable[[ProgressEvent], None]`. Each event carries the incoming stage
  label, elapsed time of the stage that just completed, and an optional
  items-processed count (commit count at the reading stage). The CLI stage
  spinner now displays per-stage elapsed time on completion lines. The service
  layer remains terminal-agnostic.
- `--format` flag added to `reveille generate`. Accepted values are `html`
  (default, existing behaviour), `json`, and `csv`. `--format json` produces
  a structured JSON file at the same path stem as the HTML output. The JSON
  payload contains repository metadata, ranked contributor statistics with all
  scoring fields, and derived health metrics. The raw commits list is excluded.
  Dates are serialised as ISO 8601 strings.
- `--format csv` added as an accepted output format, producing the ranked
  contributor table as a UTF-8 CSV file with BOM encoding. BOM ensures correct
  column rendering in Microsoft Excel on Windows without requiring a manual
  import wizard. Columns: rank, name, email, designation, tier, commits,
  lines added, lines deleted, net lines, active days, last commit date,
  composite score, percentile.

### Changed

- CodeQL security scanning and OpenSSF Scorecard workflows added to the repository.
  CodeQL scans Python source on every pull request and push to main. Scorecard
  publishes an automated security health score to the OpenSSF API on every push
  to main, enabling the Scorecard badge and providing a verifiable third-party
  security signal for enterprise evaluators.

### Fixed

- `--output` path resolution hardened against upward traversal sequences.
  Paths containing `..` components are rejected at the CLI boundary with a
  non-zero exit and an actionable diagnostic. Resolved output paths that fall
  outside the repository root emit a stderr warning rather than an error,
  making cross-boundary writes auditable in CI environments without restricting
  legitimate use cases such as writing reports to a shared output directory.
- Contributor display names and other user-controlled strings sourced from Git
  commit metadata are now sanitised before embedding as Plotly trace labels.
  HTML tags are stripped via a compiled regex, null bytes are removed, and
  surrounding whitespace is trimmed. Content-safe characters (ampersands,
  parentheses, hyphens, apostrophes) are preserved. Applied at every trace
  embedding site across all chart builders and the heatmap payload.

---

## [0.5.1] — 2026-05-26

### Fixed

- Internal `__version__` constant corrected to `"0.5.1"`. The v0.5.0 release
  was published with the constant still reading `"0.4.1"`, causing
  `reveille --version` to report the wrong version despite the correct package
  metadata being present on PyPI. A `check-version` Makefile target has been
  added to the `ci` recipe to enforce parity between `pyproject.toml` and
  `__init__.__version__` on every future pull request.

---

## [0.5.0] — 2026-05-19

### Added

- `.mailmap` alias resolution applied in `GitReader` before contributor
  aggregation. Contributors who have committed under multiple email
  addresses are now correctly unified under their canonical identity
  as declared in `.mailmap`. Repositories without a `.mailmap` file
  are unaffected. The four-field `.mailmap` form is not yet supported
  and is documented as a known limitation.
- Per-contributor weekly commit frequency chart added as a new report
  section between the aggregate commit timeline and the contributor
  rankings table. Each contributor is represented as a separate trace,
  enabling direct comparison of burst contributors versus sustained
  low-volume engagement across the analysis window.

### Changed

- Pre-commit hooks for ruff and mypy converted to `repo: local` configuration.
  Hooks now execute inside the project's Poetry virtualenv, ensuring exact
  version parity with the CI pipeline and eliminating the `additional_dependencies`
  maintenance burden in the mirror-based hook configuration.
- PyPI development status classifier updated from `3 - Alpha` to `4 - Beta`.
  Added `Intended Audience :: Information Technology` and
  `Topic :: Software Development :: Build Tools` classifiers.

### Fixed

- `validate` command now implements its documented contract in full. In
  addition to confirming the target path is a readable Git repository, it
  verifies that at least one commit is reachable on the default branch.
  Repositories with no commits exit with a non-zero status and a diagnostic
  message, making the command reliable for CI pre-flight checks.

---

## [0.4.1] — 2026-05-12

### Fixed

- Activity heatmap no longer renders as a solid blue fill for years in which
  the selected contributor has no commits. Plotly's default auto-ranging
  collapsed a flat-zero dataset to an arbitrary scale centred at zero,
  mapping all cells to a non-transparent colour and producing a negative
  colour bar axis. Explicit `zmin` and `zmax` anchors in the Plotly trace
  now ensure zero always resolves to the transparent stop in the colorscale,
  correctly displaying empty years as a blank grid.

---

## [0.4.0] — 2026-05-12

### Added

- Activity heatmap redesigned as a GitHub-style year-navigable grid.
  Rows represent days of the week (Monday–Sunday); columns represent
  calendar weeks. Year tabs derived from the analysis window allow
  switching between calendar years without regenerating the report.
  A contributor dropdown provides per-contributor views alongside the
  default aggregated view. Leap years are handled correctly through
  UTC-based date arithmetic. The four-spec embed (daily/weekly/monthly/
  yearly) is replaced by a single compact daily-count JSON payload,
  reducing embedded heatmap data size proportional to the number of
  years in the analysis window.

### Removed

- `--heatmap-granularity` CLI flag removed. The concept of switching
  between weekly/monthly/yearly chart structures is superseded by year
  navigation within a single canonical grid layout.
- `heatmap_granularity` TOML key removed from `ReportConfig` and the
  `[report]` section of `reveille.toml`. Existing configuration files
  containing this key are unaffected — the key is silently ignored by
  the TOML parser.
- `HeatmapGranularity` type alias removed from `reveille.domain.models`.

---

## [0.3.3] — 2026-05-12

### Added

- `reveille help` command that displays the top-level help text listing all
  available commands and global options. Supplements the existing
  `reveille --help` flag with a subcommand form that matches the instinctive
  typing pattern for users familiar with Git-style CLIs.
- `-h` accepted as a short form of `--help` on all commands. `reveille -h`,
  `reveille generate -h`, `reveille init -h`, and `reveille validate -h` all
  display the relevant help text. Implemented via Click's `help_option_names`
  context setting, which propagates the alias to every subcommand without
  per-command wiring.

### Fixed

- Upgraded Typer from `^0.12.0` to `^0.18.0` and removed the `click <8.3.0`
  upper bound. Click 8.3.0 (released September 2025) introduced a breaking
  change to `Parameter.make_metavar()` that caused a `TypeError` whenever
  Reveille attempted to render help output — including on bare `reveille`
  invocations due to `no_args_is_help=True`. Typer 0.18.0 restores full
  Click 8.3.x compatibility.

---

## [0.3.0] — 2026-05-08

### Added

- Progress indicator for `reveille generate`. Stage-level status lines
  are emitted to stderr as the pipeline advances through reading commit
  history, aggregating contributor statistics, ranking contributors, and
  rendering the report. Each stage animates until complete, then resolves
  to a static completion line. Stderr is used so stdout remains clean for
  scripting. Implemented via an optional `on_progress` callback on
  `generate_report`; the service layer remains unaware of the CLI.
- `reveille generate` auto-discovers `reveille.toml` at the current working
  directory when `--config` is not provided. A fully commented file applies
  all built-in defaults. A partially configured file applies only the keys
  present; absent keys fall back to defaults. A malformed file exits with a
  non-zero status, a parse error detail, and an explicit remediation hint to
  correct the syntax or regenerate the file with `reveille init --force`.
  The `--config` flag remains available for non-standard file names and
  paths.

### Changed

- Black removed as a development dependency. `ruff format` is now the
  sole formatter. `ruff format` has been Black-compatible since Ruff v0.2.0;
  running both was redundant. The `ruff-format` pre-commit hook replaces
  the `psf/black` hook at the same `ruff-pre-commit` revision.

### Fixed

- `reveille init` now validates that the current working directory is a
  Git repository root before writing the configuration file. Previously
  the command wrote the file unconditionally, producing a configuration
  that referenced a non-repository path and could not be used with
  `reveille generate`. Running `init` outside a repository root now exits
  with a non-zero status and a diagnostic message.

---

## [0.2.0] — 2026-05-06

### Added

- `reveille init` command that writes a fully annotated `reveille.toml`
  to the current directory with all configuration keys present, documented
  inline, and set to their defaults. Eliminates the need to consult
  documentation when beginning to customise the tool.
- `--output` flag for `reveille init` to write the configuration file to
  a non-default path.
- `--force` flag for `reveille init` to overwrite an existing configuration
  file without prompting.
- Client-side heatmap granularity toggle. All four heatmap specs (daily,
  weekly, monthly, yearly) are embedded in the HTML output. Toggle buttons
  allow switching between granularities via `Plotly.react()` without a page
  reload. The `--heatmap-granularity` flag controls the default view on open.
- Daily heatmap granularity. `_build_heatmap_daily` produces a GitHub-style
  layout with one cell per calendar day. The rolling window defaults to 365
  days back from the analysis window end to prevent excessive chart width.
  Available as the fourth granularity option alongside weekly, monthly,
  and yearly.

### Fixed

- CHANGELOG link in README replaced with absolute GitHub URL, resolving
  a broken relative path on the PyPI project page.
- MIT Licence link in README replaced with absolute GitHub URL, resolving
  a broken relative path on the PyPI project page.
- `reveille init` template corrected to include `"daily"` as an accepted
  `heatmap_granularity` value with inline usage guidance, consistent with
  the other three granularity options.
- Contributor ranking now correctly handles tied composite scores. Previously,
  contributors with identical composite scores all received the lowest percentile
  in their group, causing equally active contributors in small teams to be
  assigned the Private designation regardless of their output. Rank computation
  now uses `bisect.bisect_left`, which applies lower-bound percentile semantics
  and is O(log n) per lookup rather than O(n).
- `assign_tier` unreachable fallback removed. The function previously contained
  a final return of the undocumented designation "Recruit" that could never be
  reached. An `AssertionError` is now raised in its place to make any future
  `_TIER_BOUNDARIES` misconfiguration immediately visible.
- Daily heatmap chart generation unified through the `_build_heatmap_chart`
  dispatch function. The embedded daily spec and the client-side toggle path
  previously used different `window_end` anchors when `--until` extended beyond
  the latest commit date, producing silently divergent charts. Both paths now
  use `analysis_until` as the anchor.
- Exception handling in `Renderer.__init__` narrowed from bare `Exception` to
  `TemplateNotFound`, `TemplatesNotFound`, and `OSError`. Unexpected exceptions
  now propagate without being wrapped, preserving diagnostic information at the
  CLI boundary.
- `GitReader.aggregate_contributor_stats` signature corrected: `window_start`
  and `window_end` parameters documented as "stored on the returned stats" were
  never used in the function body. Both parameters have been removed and all
  call sites updated.
- `--min-commits 1` on the CLI now correctly overrides a higher `min_commits`
  value set in a `reveille.toml` configuration file. Previously, the value
  `1` was treated as equivalent to "flag not provided," causing the config
  file value to win silently and violating the documented CLI precedence rule.
  The parameter now uses `None` as its sentinel, allowing explicit `1` to be
  distinguished from the absence of the flag.
- `HeatmapGranularity` type alias consolidated to `reveille.domain.models`,
  eliminating a triplicate definition across `config.py`, `renderer.py`, and
  the TOML validation block. Both layers now import the canonical definition
  from the domain; the validation tuple is derived via `get_args` so it stays
  in sync automatically. The error message for invalid TOML values now lists
  accepted options derived from the type.
- `RankingWeights` sum validation tolerance relaxed from `1e-9` to `1e-6`.
  The previous threshold was unnecessarily strict for user-supplied decimal
  weights, where IEEE 754 rounding could plausibly produce deviations
  approaching `1e-9` despite representing an exact decimal sum of `1.0`.

---

## [0.1.1] — 2026-04-30

### Fixed

- Documentation link in README now points to the absolute GitHub URL for
  `docs/USER_GUIDE.md`, resolving a broken relative path on the PyPI project page.
- Makefile recipe indentation corrected from spaces to tabs, resolving
  `missing separator` errors on strict Make implementations (PR #16).

---

## [0.1.0] — 2026-04-30

### Added

- Project README covering installation, quickstart, CLI reference,
  contributor ranking system, configuration schema, and contribution guidelines.
- Comprehensive User Guide at `docs/USER_GUIDE.md` covering every CLI flag,
  every TOML key, the ranking algorithm in plain language, report interpretation
  guidance, and practical patterns for common use cases.
- `pyproject.toml` with full Poetry configuration and tool settings
  for ruff, mypy, pytest, and coverage.
- `poetry.lock` for reproducible dependency resolution.
- `.gitignore` scoped to a Python CLI project using Poetry.
- Domain models: `Commit`, `ContributorStats`, `RankedContributor`,
  `RepositoryMetadata`, `ReportData`.
- Domain exception hierarchy under `reveille.exceptions`.
- Configuration models: `ReportConfig`, `RankingWeights` with validation.
- `GitReader` adapter with full integration test coverage.
- Ranking engine with weighted composite scoring and tier assignment.
- `Renderer` adapter, Jinja2 HTML template, and report service.
- Typer CLI with `generate`, `validate`, and `version` commands.
- TOML configuration file support with full CLI flag precedence.
- Dark mode toggle with localStorage persistence.
- Heatmap granularity control: `weekly`, `monthly`, `yearly` views,
  exposed as `--heatmap-granularity` CLI flag and TOML key.
- Commit share and lines share donut charts.
- Tier badges in the contributor ranking table with solid fill for
  tiers III–VII and outlined style for tiers I–II.
- Score bar with gradient fill and comma-formatted numeric columns.
- `pytest-timeout` added to the development dependency group with a
  120-second global ceiling.
- GitHub Actions CI workflow running lint, typecheck, and test jobs in
  parallel across Python 3.11 and 3.12.
- Makefile with standard development targets.
- Pre-commit configuration with ruff, black, and mypy hooks.
- MIT licence.

### Changed

- Tier designation strings updated to a consistent NATO-aligned military
  rank progression: Private, Corporal, Sergeant, Lieutenant, Captain,
  Major, Commander. The previous set mixed military terminology with
  professional titles inconsistently. Commander is retained at tier VII.
- Heatmap x-axis coercion fixed: all three heatmap builders now set
  `xaxis.type` to `"category"`, preventing Plotly from silently treating
  ISO 8601 label strings as timestamps. The weekly builder's column
  labels changed from `.isoformat()` to `.strftime("%b %d")`.
- `addopts` in `pyproject.toml` stripped of runtime flags (`-n auto`,
  coverage instrumentation). Parallelism and coverage are now supplied
  explicitly at the call site in the Makefile and CI workflow.
- Coverage `data_file` path corrected from `.coverage_data/.coverage`
  to `.coverage`, eliminating a worker deadlock under `pytest-xdist`.
- `test_output_file_has_no_external_script_tags` rewritten to use a
  targeted regex against `<script[^>]+src=["']https?://` rather than a
  bare substring check, eliminating a false positive against the embedded
  Plotly bundle and a `difflib` O(n²) hang on assertion failure.
- Module-level `_PLOTLY_JS_BUNDLE` constant introduced in the renderer,
  replacing a per-call `plotly.offline.get_plotlyjs()` invocation.
  Reduces end-to-end test suite runtime from approximately 40 minutes
  to under two minutes.
- Pre-commit ruff hook revision updated from `v0.14.5` to `v0.15.7`.
  Hook identifier updated from the legacy `ruff` alias to `ruff-check`.
- Weekly commit timeline x-axis coercion fixed: `xaxis.type` set to
  `"category"` and `tickangle` to `-45`, eliminating timestamp-format
  tick labels produced by Plotly's implicit date coercion.

---

[Unreleased]: https://github.com/varaprasadchilakanti/reveille/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.8.0
[0.7.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.7.0
[0.6.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.6.0
[0.5.1]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.5.1
[0.5.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.5.0
[0.4.1]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.4.1
[0.4.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.4.0
[0.3.3]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.3.3
[0.3.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.3.0
[0.2.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.2.0
[0.1.1]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.1.1
[0.1.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.1.0
