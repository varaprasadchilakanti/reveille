# 0008 — Output records its own provenance and declares a schema version

**Status:** Accepted

## Context

Through v0.7.0 a Reveille report stated numbers without stating what produced them.
The `metadata` block described the *repository* — name, remote, commit count, window
dates — and nothing described the *analysis*.

Three consequences, each observed rather than hypothesised:

**Two reports that disagree could not be reconciled.** Nothing recorded which filters
were applied. `--exclude-author` removing three bots, or `--min-commits 5` dropping
half the contributors, changed the numbers and left no trace. Worse, `since` and
`until` appeared only as resulting *values*: a reader could not distinguish "the full
history, which happens to begin in March" from "filtered to begin in March".

**A consumer had no way to detect a breaking change.** v0.7.0 renamed
`derived.bus_factor` to `derived.commit_concentration` (ADR 0005). A pipeline reading
the old key got a `KeyError` at runtime, with nothing in the payload to say which
shape it was parsing. Every future output change would repeat that.

**Output was not reproducible.** Two runs over an identical repository produced
byte-different files. The difference was `generated_at`, but `analysis_until` also
defaulted to `date.today()`, which feeds the recency component of the ranking — so
scores drifted across midnight for an unchanged repository. An auditor could not
re-run the tool and compare.

And underneath all three, a defect that made provenance actively misleading:
`RepositoryMetadata.default_branch` held neither the default branch nor the analysed
one. It was recomputed from whatever was checked out, ignoring `--branch`. A report
generated with `--branch main` from a feature checkout named the feature branch — in
the JSON *and* in the HTML, which renders it as "Branch:". On `main` all three
meanings coincide, which is why it survived. No test covered it; the only references
were unit fixtures hardcoding `default_branch="main"`, and a fixture that asserts its
own input cannot catch a value computed from the wrong source.

## Decision

**The branch field is renamed and corrected first.** `analysed_branch` holds the ref
the analysis actually walked, passed through from the caller rather than recomputed.
This is a **breaking JSON key change**, accepted pre-1.0 on the same reasoning as
ADR 0005: a name with an established meaning attached to a different quantity is a
defect, and carrying it into a stable API would be worse.

**Every output carries an `AnalysisProvenance` block**: the Reveille version, the
analysed HEAD SHA, the filters *as requested* (`requested_branch`, `requested_since`,
`requested_until`, `exclude_authors`, `min_commits`), whether a `.mailmap` was
applied, whether ranking was enabled and under which weights, and whether the run was
deterministic. Ranking weights are `null` when ranking is off, because reporting
weights that were never applied would be a false statement.

**`schema_version` is the first key in the JSON document**, so a consumer can decide
whether it can parse the rest before trying. It starts at `1.0` and is independent of
the release version: it changes when the shape changes, not when the tool does. Major
for a removal or rename, minor for a purely additive field.

**`--deterministic` makes output byte-reproducible.** It pins `generated_at` to the
timestamp of the analysed HEAD commit, the way a reproducible build pins to
`SOURCE_DATE_EPOCH` — the value stays meaningful and stops being a function of when
the command ran. It also closes the analysis window on the last commit rather than on
`date.today()`, because otherwise the ranking's recency component still varies with
the clock and the output is not reproducible in any useful sense.

## Consequences

**Breaking for JSON consumers**, twice over: `metadata.default_branch` is gone, and
the payload has two new top-level keys. That is precisely why `schema_version` ships
in the same release — this is the last output change a consumer has no way to detect.

**`--deterministic` changes the numbers, not just the bytes.** Closing the window on
the last commit rather than today alters recency scores. It is opt-in for that
reason, and provenance records that it was used, so a deterministic report is never
silently comparable with a normal one.

**Provenance is a privacy surface.** It records exclusion patterns, which may name
individuals, into a document intended to be shared. This is a smaller instance of
something already true of the report — contributor email addresses are written into
it — and it does not change the shape of that problem, but it does add to it.

**What this does not do.** There is no content hash and no signature. The report says
what produced it; it does not prove it. Provenance is self-asserted, exactly like the
git author metadata it summarises, and neither is evidence against a determined liar.
It is evidence against confusion, which is the far more common problem.
