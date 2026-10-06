# 0016 — The repository profile's shape returns, as six separate petals above the table

**Status:** Proposed. Supersedes the "no shape" part of ADR 0012; its table, its reference
values and its reasons stand.

## Context

ADR 0012 replaced a five-axis radar with a three-row table. Its reasons were measured and stay
true: two axes restated other figures, the radar's area depended on an arbitrary axis order and
was read less accurately than length, screen readers received a stale label, and bare shares had
no reference point.

The author asked for the shape back: readers recognise a profile at a glance, and the dimensions
they bring to a repository — is it steady, is it current, is it one person, do people work
together, is it reworking itself, how much is automation — do not all appear in three rows.

The literature says which shape. Albo, Lanir, Bak and Rafaeli (*Off the Radar*, IEEE TVCG 2016)
compared radial designs for multi-part indicators: the radar was the least effective and least
liked; the flower chart, separate petals as in the OECD Better Life Index, was preferred. Fuchs,
Isenberg, Bezerianos, Fischer and Bertini (IEEE TVCG 2014) found star glyphs are compared more
reliably without a connecting contour. Both point away from a filled polygon and towards separate
marks of length.

## Decision

- **A flower of six petals sits above the existing table.** Each petal's length is its share, from
  0% at the centre to 100% at the rim; petals are separate wedges, never joined into a polygon,
  so no area depends on axis order. Each carries its value as text, and where an expectation can
  be computed (ADR 0012) a mark across the petal shows it.
- **The table stays** with every figure in it: for exact reading, for screen readers, and for a
  reader without JavaScript. The flower is inline SVG drawn by the template, coloured by the
  theme's own properties, so it too renders without JavaScript and prints; no chart library and
  no new Plotly trace type is involved.
- **Six measures, in a fixed order, each a share between 0 and 1:**
  1. *Continuity* — weeks with a commit (ADR 0012; expectation computed).
  2. *Recent work* — commits in the final quarter of the window (ADR 0012; expectation computed).
  3. *Shared* — commits not made by the single busiest author. Expected under an even split
     across *n* authors: 1 − 1/*n*.
  4. *Collaboration* — commits that credit a co-author (ADR 0014). No expectation.
  5. *Revisiting* — files touched by more than one commit (ADR 0012). No expectation.
  6. *Automation* — commits by automated accounts (the `[bot]` rule of ADR 0013). No expectation.
- **None is a target, and the section says so**, as it does today.

## Consequences

**`Shared` partly restates the distribution findings**, the trade ADR 0012 refused for `Spread`.
It is kept because "is this one person?" is the question readers bring, and a petal answers it
at a glance; unlike `Spread` it is a plain share of commits rather than a transform of the Gini,
and its expectation is computed. The Gini remains the measure of distribution.

**The profile reads identities again**, as commit authors and trailers, to compute `Shared`,
`Collaboration` and `Automation`. It still names nobody and counts no person's work in the output.

**Petal area grows with the square of its length.** Values are printed on every petal and in
the table, so nothing has to be read from area; the caption says length encodes the share.

**One more drawing to keep accessible.** The SVG carries a label listing every value, and the
table remains the authoritative text.
