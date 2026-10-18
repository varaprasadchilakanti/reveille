# Architecture

How Reveille is built and why. It is written for someone about to change the code, and it
describes the system as it exists. If a statement no longer holds, the statement is the bug: fix
it in the same pull request as the code that outdated it.

To use Reveille, see [USER_GUIDE.md](USER_GUIDE.md). For individual decisions, see [adr/](adr/).

---

## What Reveille is

A command-line tool that reads a local Git repository and writes a single self-contained HTML file
describing its commit history. Three properties constrain nearly every decision; a change that
breaks one changes what the product is, and needs to be argued as such.

It does not change Git data (history, refs, index, objects or configuration). Reveille opens a
repository, reads history, and writes one output file. It refuses any output path inside `.git`
and never runs a mutating Git command. The report goes where you point it, by default
`reveille-report.html` in the repository root, which for a working tree is inside the working
tree.

It is offline. Nothing is transmitted, and a partial clone is refused because Git would fetch the missing objects. The report loads no CDN, no web font and no remote
image; the ~4.8 MB Plotly bundle is embedded in the file. A test asserts that no `<link>`,
`<script>` or `<img>` in the template references a remote host.

It is a single file: one HTML document with no sidecar assets, openable from a download folder
on a machine with no network.

---

## The dependency rule

```
  cli.py  ─────►  services/  ─────►  domain/  ◄─────  adapters/
                                        ▲
                                        │
                                    config.py
```

Dependencies point inward. The domain knows nothing about how commits are read or reports drawn.

| Layer | May import | Must not import |
|---|---|---|
| `domain/` | stdlib, `config.py` | GitPython, Plotly, Jinja2, Typer |
| `adapters/` | stdlib, `domain/`, `exceptions.py`, `replacing.py`, its own framework | `services/`, `cli.py` |
| `services/` | `domain/`, `adapters/`, `config.py` | Typer, GitPython, Plotly, Jinja2 |
| `cli.py` | `services/`, `config.py`, `exceptions.py` | GitPython, Plotly, Jinja2 |

Framework ownership is exclusive: `adapters/git_reader.py` is the only module that imports
GitPython, `adapters/renderer.py` the only one that imports Plotly or Jinja2, and `cli.py` the only
one that imports Typer. Reading history from another source, or rendering another format, then
means writing one adapter. `tests/unit/test_layering.py` enforces this by importing each layer in a
clean interpreter and asserting which frameworks appear in `sys.modules`.

### One exception

`domain/ranking.py` imports `RankingWeights` from `config.py`, which is a Pydantic model. So the
domain is not literally free of third-party imports: it transitively imports Pydantic.

This is deliberate. `RankingWeights` is a value object whose only
behaviour is validating that four weights sum to 1.0, and Pydantic is the project's validation
library. A plain-dataclass copy would be two definitions of one concept that can drift apart.

The rule is that the domain imports no I/O and no presentation framework. It reads nothing,
writes nothing and draws nothing, which is what makes the ranking engine testable without a
repository on disk.

---

## Module map

```
src/reveille/
    __init__.py       __version__; installs a logging NullHandler
    __main__.py       python -m reveille
    cli.py            Typer app, exit codes, progress display
    config.py         Pydantic config models and TOML loading
    init.py           reveille.toml and .mailmap scaffold generation
    replacing.py      writes a file by replacing its name, so a hard link is never written through
    capabilities.py   the machine-readable self-description: what the tool can and cannot do
    exceptions.py     the exception hierarchy
    py.typed          PEP 561 marker
    domain/
        models.py     frozen dataclasses; no behaviour beyond derived properties
        ranking.py    scoring and tiering (opt-in)
        concentration.py  Lorenz curve and Gini coefficient; names no author
        summary.py    the written findings, by fixed rules over the numbers
        files.py      churn per path, hotspots, change by file type
        profile.py    the six-axis repository profile
        areas.py      who changed each area (opt-in, ADR 0013)
        coauthors.py  Co-authored-by credits, kept apart from authorship
        brief.py      what changed since a point, in counts (ADR 0022)
        state.py      the repository's present state (ADR 0024)
        pseudonyms.py every address replaced by a per-report token (--hide-emails)
    adapters/
        git_reader.py GitPython in; domain models out
        renderer.py   domain models in; HTML, JSON or CSV out
    services/
        report.py     generate_report, the pipeline
    templates/
        report.html.j2
```

---

## Domain model

Frozen dataclasses in `domain/models.py` carry data and derived properties, never I/O. Their
fields are listed there; this section keeps only what the code does not say. `ReportData` is the
sole input to `Renderer`.

`analysed_branch` is the ref the analysis walked. It was called `default_branch` through v0.7.0
and held neither the default branch nor the analysed one
([ADR 0008](adr/0008-output-provenance-and-schema-version.md)).

**`CoAuthor`** and `Commit.co_authors` are identities a `Co-authored-by` trailer credits, read in a
separate NUL-separated pass that must line up with `rev-list` one for one and resolved like
authors (ADR 0014). `domain/coauthors.py` lists those credited only as co-authors; authorship
figures never use them.

**`AreaActivity`** is collected only under `--area-authors`; `domain/areas.py` turns it into
statements that name authors alphabetically and never print a per-person count or date.

The requested/resolved distinction is the point of provenance: `analysis_since` records where the
window began, `requested_since` whether anybody asked for it. `exclude_authors_count` is a count,
because naming the excluded in provenance would put them back.

**`ProgressEvent`** is emitted by the service; the CLI decides whether to animate, log or ignore
it. The service has no opinion about terminals.

---

## Error model

```
ReveilleError
├── RepositoryError
│   └── EmptyRepositoryError
├── ConfigurationError
└── RenderError
    └── OutputPathError
```

Everything Reveille raises across a layer boundary descends from `ReveilleError`, so the CLI can
catch one type and be sure nothing escapes as a traceback. Adapters raise the specific subclass;
the CLI maps it to an exit code. `RevelleError`, the original misspelling, survives only as a
deprecated alias through a module-level `__getattr__` (PEP 562) that emits a `DeprecationWarning`;
it is absent from `__all__`.

### Exit codes

`cli.ExitCode` is part of the public contract:

| Code | Meaning |
|---|---|
| `0` `SUCCESS` | Ran; answer affirmative. |
| `1` `NEGATIVE` | Ran correctly; answer negative, such as an analysis window with no commits. |
| `2` `CANNOT_RUN` | Could not run: bad invocation, bad config, unreadable repository, unwritable output. |

The split follows `grep` and `diff`: a negative answer is not an inability to answer. A CI job can
accept an empty window and fail on an unreadable repository. Finer causes belong in stderr;
a code per cause does not scale and would break callers branching on the old numbering.

---

## The pipeline

`services/report.py::generate_report(config, on_progress=None)` runs up to four stages, emitting a
`ProgressEvent` before each:

1. **Reading commit history**: `GitReader.read_commits`
2. **Aggregating contributor statistics**: `GitReader.aggregate_contributor_stats`
3. **Ranking contributors**: `domain.ranking.rank_contributors` (only when ranking is enabled)
4. **Rendering report**: `Renderer.render` / `render_json` / `render_csv`

With `ranking_enabled=False`, stage 3 still produces `RankedContributor` objects with `tier=0`,
designation `"--"` and zeroed score and percentile, so the pipeline needs no branch. Every
renderer does branch, on `provenance.ranking_enabled` rather than on the list being non-empty.
The placeholders must never reach a reader: HTML drops the rank, designation and score columns
and retitles the section, and CSV omits the designation and score columns as JSON omits those
keys. The `rank` field itself, the position in table order by commits, is still written to JSON
and CSV. Gating on `ranked_contributors` instead shipped a "Contributor Rankings" table full
of zeroes into the default report.

### Reading history

`read_commits` reads the history in one `git log --numstat` pass rather than asking GitPython for
per-commit stats, because `Commit.stats` shells out to `git diff` once per commit. Beside it run a
`git rev-list --no-merges` that authenticates each record and a second `git log` that reads only
`Co-authored-by` trailers ([ADR-0019](adr/0019-how-history-is-read.md), which supersedes
[ADR-0004](adr/0004-single-pass-numstat-read.md)). Timings are in the
[User Guide](USER_GUIDE.md#how-reveille-works). Merge commits are excluded unconditionally
([ADR-0001](adr/0001-exclude-merge-commits.md)). An unborn `HEAD` raises `EmptyRepositoryError`,
which the CLI maps to `NEGATIVE`: readable, but nothing to report.

### Identity resolution

Contributors are keyed on lowercased email ([ADR-0002](adr/0002-email-as-identity-key.md)). Two
normalisations run first. **`.mailmap`**: all four `gitmailmap(5)` forms, matched
most-specific-first (name and email, then email, then name), case-insensitively, with malformed
lines skipped silently as Git does. **GitHub noreply addresses** fold on the account number; a legacy
address joins an account only when one account used its username (ADR 0023).

### Rendering

`_build_charts` returns one entry per chart: a Plotly JSON string, or the string `"null"` when
there is nothing to draw, so the template decides what the page looks like. The heatmap is the
exception. It ships a compact daily-count payload and client-side JavaScript builds the Mon-Sun
grid over the window's weeks, because a per-day Plotly spec for a multi-year repository is far
larger than the counts it encodes.

JSON written into a `<script>` block has every `<` escaped to `\u003c` (`_script_safe`).
Without it, a name containing `</script>` would close the block and run as markup, and an
unfinished HTML comment would blank every chart.
`_sanitise_chart_label` strips HTML tags from labels. Jinja autoescaping is on but does not apply
inside a JSON script block, which is why the escaping is explicit.

`_to_json` strips `paper_bgcolor`, `plot_bgcolor` and `font.color` from the serialised layout.
Theme colours are supplied client-side, and a theme toggle re-plots every chart through the same
path as the first paint, deliberately not `Plotly.relayout()`, which replaces any nested container
it is handed and does not touch the trace-level colorscale the heatmap's two ramps depend on.
`_PLOTLY_JS_BUNDLE` is read once at import, because `get_plotlyjs()` reads ~4.8 MB per call.

---

## Configuration

`ReportConfig` (Pydantic) lives in `config.py`; a validator enforces `since < until`.
`RankingWeights` holds `commits=0.30`, `lines=0.25`, `consistency=0.25`, `recency=0.20`, each in
`[0, 1]`, with a validator enforcing that they sum to 1.0 within `1e-6`. `load_config_from_toml`
reads via stdlib `tomllib` and flattens `[report]`, `[filters]`, `[ranking]` and `[areas]` into a
`ReportConfigKwargs` `TypedDict`.

**An explicitly provided CLI flag always beats the config file.** `min_commits` carries a `None`
sentinel for this reason: without it, `--min-commits 1` is indistinguishable from "not provided",
and a config file setting `min_commits = 2` would silently win.

---

## Ranking

Four components are min-max normalised, combined by weighted sum, then converted to percentiles
and tiers. Consistency is already in `[0, 1]` and passes through `_normalise_scores` unchanged;
when max equals min, every value resolves to 1.0. Recency bins commits by ISO week, weights the
anchor week 1.0, and decays each earlier week by `_RECENCY_DECAY = 0.85`. Percentiles use
`bisect.bisect_left`, so tied scores get identical percentiles
([ADR-0003](adr/0003-bisect-left-for-percentile-ties.md)).

`assign_tier` walks `_TIER_BOUNDARIES` top-down on strict `>`:

| Percentile above | Tier | Designation |
|---|---|---|
| 95.0 | 7 | Commander |
| 88.0 | 6 | Major |
| 75.0 | 5 | Captain |
| 60.0 | 4 | Lieutenant |
| 40.0 | 3 | Sergeant |
| 20.0 | 2 | Corporal |
| −1.0 | 1 | Private |

The `-1.0` entry is an exhaustive fallback. `assign_tier` raises `AssertionError` if nothing
matches, which is unreachable in production and a loud signal that `_TIER_BOUNDARIES` was
misconfigured; it replaced a silent default that would have hidden exactly that.

> On interpreting these numbers: the ranking measures commit and line volume. It does not measure
> contribution, and the tier names are labels on that score, not an evaluation of anyone. The SPACE framework holds that "developer productivity is about more than an
> individual's activity levels"; DORA's metrics describe applications and services, not people.
> The ranking shows the shape of participation, not a grade. See the User Guide for the caveat that
> ships to users.

---

## Testing

| Tier | Location | Rule |
|---|---|---|
| Unit | `tests/unit/` | Inputs constructed directly. No Git repository on disk, except the architecture and gate tests that run a subprocess on purpose. |
| Integration | `tests/integration/` | Real Git repositories built by fixtures via `subprocess`. |
| E2E | `tests/e2e/` | Full CLI invocation through Typer's `CliRunner`. |

The suite runs under `pytest-xdist` (`-n auto`). Repository fixtures are module-scoped and use
`tmp_path_factory`, which is worker-safe where `tmp_path` is not. The coverage gate is 90%.

Several tests protect properties that could erode unnoticed; know them before changing what they cover:

- **Offline moat**: no `<link>`, `<script>` or `<img>` in the output references a remote host, no
  chart label carries markup, and the report's Content-Security-Policy allows no network source.
- **Layering**: no framework import crosses the boundaries above.
- **Contrast**: WCAG AA ratios computed from the template's own CSS custom properties.
- **Packaging**: the `py.typed` marker is present in both wheel and sdist.
- **Workflow pins**: every GitHub Action is pinned to a commit SHA with a comment naming a precise version.

---

## Toolchain

| Tool | Role |
|---|---|
| Poetry | Dependencies, virtualenv, build, publish |
| ruff | Lint (E,W,F,I,C,B,UP,N,SIM,D,RUF) and format; the sole formatter |
| mypy `strict` | Type checking |
| pytest + xdist + cov | Testing, parallelism, coverage |
| pre-commit (`repo: local`) | ruff and mypy inside the Poetry venv, so versions cannot diverge from CI |
| GitHub Actions | CI across Python 3.11-3.14; publish on `v*` tag |
| PyPI OIDC trusted publisher | No stored credentials; PEP 740 attestations |

`make ci` runs the checks that need no network or GitHub; CI adds the Python matrix, actionlint,
the vulnerability scan, the reproducible-build check, CodeQL and the CLA gate. Run `make ci`
before opening a pull request.

---

## Lineage

Almost nothing here is novel. Each choice below names the established technique behind it, so it can be checked against the literature.

| In this codebase | Established as |
|---|---|
| `CLI → Service → Domain ← Adapters` | **Ports and adapters** (Cockburn, 2005), or *hexagonal architecture*. The domain depends on no I/O and no presentation framework. |
| `test_layering.py`, `test_workflow_pins.py`, `test_lockfile.py`, `test_licence.py`, `test_capabilities.py`, `test_docs_links.py` | **Architectural fitness functions** (Ford, Parsons and Kua, *Building Evolutionary Architectures*, 2017): the build fails when a structural property stops holding, not only when a feature breaks. |
| Refusing a revision that begins with `-`; accepting only object names `git rev-list` produced; refusing to write through a symlink; guards that exit non-zero when they cannot check | **Fail-safe defaults** and **complete mediation** (Saltzer and Schroeder, 1975): the default is refusal, and every write passes the same check. |
| `AnalysisProvenance` on every JSON report | **Data provenance**: a figure that cannot state what it measured, over what, with which filters, is not evidence. |
| `schema_version` as the first key | **Schema versioning**: a consumer decides whether it can parse before it tries. |
| The Lorenz curve and Gini coefficient | **Lorenz (1905)**, **Gini (1912)**: standard instruments for concentration, with a century of interpretation and documented weakness. |
| `domain/summary.py`, the written findings | **Data-to-text generation** (Reiter and Dale, 2000): rules over computed statistics, realised through fixed templates. Deterministic, offline, no model. |
| `domain/files.py`, churn and hotspots | **Relative code churn** (Nagappan and Ball, ICSE 2005); **hotspot analysis** (Tornhill, 2013). Churn is added plus deleted. The full method crosses churn with complexity; Reveille receives paths and line counts, not contents, so it reports churn alone and says so under the chart. |
| `domain/profile.py`, six shares as separate petals beside a table | **Graphical perception** (Cleveland and McGill, JASA 1984); **radial indicators** (Albo et al., IEEE TVCG 2016). Length is read more accurately than area, and a radar's area depends on axis order (ADR 0012). Each share is a separate petal, never a joined polygon, and the table is the authoritative figure (ADR 0016). |
| `_CATEGORICAL_PALETTE`, four series at most | **Color Universal Design** (Okabe and Ito, 2008); **dichromat simulation** (Viénot, Brettel and Mollon, 1999); **WCAG 2.1**. Over a 29-candidate pool the largest set satisfying all three constraints is four, so beyond four the report aggregates. `tests/unit/adapters/test_palette.py` recomputes it. |
| `.mailmap` handling | **`gitmailmap(5)`**: a `.mailmap` that works with `git shortlog` works here. |
| `docs/adr/` | **Architecture decision records** (Nygard, 2011): immutable once accepted; a changed decision gets a new record that supersedes the old. |
| `CHANGELOG.md`, version numbers | **Keep a Changelog**, **Semantic Versioning**. Under `0.y.z` a minor bump may break. |
| Trusted Publishing, PEP 740, a CycloneDX SBOM, SHA-pinned actions | **Software supply chain integrity** (SLSA-adjacent; OpenSSF Scorecard): did this artefact come from this repository's release workflow? |

Two things are local judgements rather than techniques. The first is that scores, tiers and
designations are off by default ([ADR 0010](adr/0010-ranking-is-opt-in.md)), with that stated in
machine-readable form so a program reading `reveille capabilities` is told what the tool is not
for. The second is that a guard counts only once it has been seen to fail: each check was tried
by reintroducing the defect it covers.
