# Architecture

This document describes how Reveille is built and, more importantly,
*why* it is built that way. It is written for someone about to change the
code.

It describes the system **as it exists**, not as it was once intended.
Every claim here was checked against the source when written. If you
find a statement that no longer holds, the statement is the bug — fix it
in the same pull request as the code that outdated it.

For how to *use* Reveille, see [USER_GUIDE.md](USER_GUIDE.md). For
individual decisions and the reasoning behind them, see
[adr/](adr/).

---

## What Reveille is

A command-line tool that reads a local Git repository and writes a
single self-contained HTML file describing its contribution history.

Three properties constrain nearly every design decision, and are worth
stating before anything else:

**It is read-only.** Reveille opens a repository, reads history, and
writes one output file at a path you name. It never writes to `.git`,
never creates commits or branches, and never runs a mutating Git
command. Anything that would change repository state is out of scope by
construction, not by omission.

**It is offline.** Nothing is transmitted anywhere. The generated report
loads no CDN, no web font, and no remote image — the ~3.5 MB Plotly
bundle is embedded in the file itself. This is what makes the output
safe to attach to an email or embed in Confluence, and it is enforced by
a test asserting no `<link>`, `<script>`, or `<img>` in the template
references a remote host.

**It is a single file.** The report is one HTML document with no
sidecar assets. A stakeholder can open it from a download folder on a
machine with no network connection.

These are not incidental. A change that breaks any of the three is a
change to what the product *is*, and needs to be argued as such.

---

## The dependency rule

```
  cli.py  ─────►  services/  ─────►  domain/  ◄─────  adapters/
                                        ▲
                                        │
                                    config.py
```

Dependencies point inward. The domain knows nothing about how commits
are read or how reports are drawn.

| Layer | May import | Must not import |
|---|---|---|
| `domain/` | stdlib, `config.py` | GitPython, Plotly, Jinja2, Typer |
| `adapters/` | stdlib, `domain/`, its own framework | `services/`, `cli.py` |
| `services/` | `domain/`, `adapters/`, `config.py` | Typer, GitPython, Plotly, Jinja2 |
| `cli.py` | `services/`, `config.py`, `exceptions.py` | GitPython, Plotly, Jinja2 |

Framework ownership is exclusive, and deliberately so:

- `adapters/git_reader.py` is the **only** module that imports GitPython.
- `adapters/renderer.py` is the **only** module that imports Plotly or Jinja2.
- `cli.py` is the **only** module that imports Typer.

The point is substitutability. Reading history from a different source,
or rendering to a different format, means writing one new adapter — not
tracing framework calls through the codebase.

`tests/unit/test_layering.py` enforces this by importing each layer in a
clean interpreter and asserting which frameworks appear in
`sys.modules`. A layering violation fails the suite rather than being
noticed in review, or not noticed.

### One honest exception

`domain/ranking.py` imports `RankingWeights` from `config.py`, which is
a Pydantic model. So the domain is not literally free of third-party
imports — it transitively imports Pydantic.

This is a deliberate trade, not an oversight. `RankingWeights` is a
value object whose only behaviour is validating that four weights sum to
1.0, and Pydantic is the project's validation library. Duplicating it as
a plain dataclass would mean two definitions of the same concept that
can drift apart.

What the rule actually protects is stated precisely: **the domain
imports no I/O and no presentation framework.** It reads nothing,
writes nothing, and draws nothing. That is the property that makes the
ranking engine testable without a repository on disk, and it holds.

---

## Module map

```
src/reveille/
    __init__.py       __version__; installs a logging NullHandler
    cli.py            Typer app, exit codes, progress display
    config.py         Pydantic config models and TOML loading
    init.py           reveille.toml and .mailmap scaffold generation
    exceptions.py     the exception hierarchy
    py.typed          PEP 561 marker — this package ships type information
    domain/
        models.py     frozen dataclasses; no behaviour beyond derived properties
        ranking.py    the scoring and tiering algorithm
    adapters/
        git_reader.py GitPython in; domain models out
        renderer.py   domain models in; HTML, JSON, or CSV out
    services/
        report.py     generate_report — the pipeline
    templates/
        report.html.j2
```

---

## Domain model

All frozen dataclasses in `domain/models.py`. They carry data and
derived properties, never I/O.

**`Commit`** — `sha`, `author_name`, `author_email`, `timestamp`,
`lines_added`, `lines_deleted`. Property: `lines_changed`.

**`ContributorStats`** — `name`, `email`, `commit_count`,
`lines_added`, `lines_deleted`, `active_days`, `first_commit_date`,
`last_commit_date`. Properties: `net_lines`, `lines_changed`.

**`RankedContributor`** — wraps `stats` with `composite_score`,
`percentile`, `tier`, `tier_designation`.

**`RepositoryMetadata`** — `name`, `remote_url`, `default_branch`,
`total_commits`, `unique_contributors`, `analysis_since`,
`analysis_until`, `generated_at`.

**`ProgressEvent`** — `stage`, `elapsed_seconds`, `items_processed`.
The service emits these; the CLI decides whether to animate them, log
them, or ignore them. The service has no opinion about terminals.

**`ReportData`** — `metadata`, `ranked_contributors`, `commits`. The
sole input to `Renderer`.

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

Everything Reveille raises across a layer boundary descends from
`ReveilleError`, so the CLI can catch one type and be sure nothing
escapes as a traceback. Adapters raise the specific subclass; the CLI
maps it to an exit code.

`RevelleError` — the original misspelling — remains available as a
deprecated alias via a module-level `__getattr__` (PEP 562). It emits a
`DeprecationWarning` and is scheduled for removal in v1.0.0. It is
absent from `__all__`.

### Exit codes

`cli.ExitCode` is part of the public contract:

| Code | Meaning |
|---|---|
| `0` `SUCCESS` | Ran; answer affirmative. |
| `1` `NEGATIVE` | Ran correctly; answer negative — an analysis window with no commits. |
| `2` `CANNOT_RUN` | Could not run: bad invocation, bad config, unreadable repository, unwritable output. |

The split follows `grep` and `diff`, distinguishing *a negative answer*
from *an inability to answer*. That is the distinction a CI job acts on:
an empty window may be an acceptable state to record; an unreadable
repository is a broken pipeline step. Finer causes belong in the stderr
message — encoding each one as its own code does not scale, and every
addition would break callers branching on the old numbering.

---

## The pipeline

`services/report.py::generate_report(config, on_progress=None)` runs
four stages, emitting a `ProgressEvent` before each:

1. **Reading commit history** — `GitReader.read_commits`
2. **Aggregating contributor statistics** — `GitReader.aggregate_contributor_stats`
3. **Ranking contributors** — `domain.ranking.rank_contributors`
4. **Rendering report** — `Renderer.render` / `render_json` / `render_csv`

With `ranking_enabled=False`, stage 3 still produces
`RankedContributor` objects, with `tier=0`, designation `"--"`, and
score and percentile zeroed. The shape stays constant so the renderer
has no branch for it.

### Reading history

`read_commits` runs a single `git log --numstat` and parses the output,
rather than iterating commits and asking GitPython for per-commit
stats. The reason is that `Commit.stats` shells out to `git diff` once
per commit; the single-pass read measured **9.4× faster** on this
repository (7.2 ms/commit → 0.77 ms/commit), which is the difference
between roughly six minutes and forty seconds on a 50,000-commit
repository. Output was verified byte-identical against the previous
implementation before the change landed. See
[ADR-0004](adr/0004-single-pass-numstat-read.md).

Merge commits are excluded unconditionally — see
[ADR-0001](adr/0001-exclude-merge-commits.md).

An unborn `HEAD` — a repository that is readable but has no commits at
all — raises `EmptyRepositoryError`, which the CLI maps to `NEGATIVE`.
It is a negative answer, not a failure to read.

### Identity resolution

Contributors are keyed on lowercased email — see
[ADR-0002](adr/0002-email-as-identity-key.md). Two normalisations run
before that key is taken:

**`.mailmap`**, all four forms from `gitmailmap(5)`, matched
most-specific-first: name-and-email → email-only → name-only. Matching
is case-insensitive. Malformed lines are skipped silently, matching
Git's own behaviour.

**GitHub noreply addresses.** Both the legacy
`username@users.noreply.github.com` and the post-2017
`12345678+username@users.noreply.github.com` forms exist, and the same
person often appears under both. The numeric prefix is stripped so they
fold together.

### Rendering

`_build_charts` returns a dict keyed `timeline`,
`contributor_timeline`, `heatmap`, `contributor_commits`,
`contributor_lines`, `pie_commits`, `pie_lines`. Each value is a Plotly
JSON string, or the string `"null"` when there is nothing to draw —
the template checks for that sentinel rather than the renderer deciding
what the page looks like.

The heatmap is the exception: it ships a compact daily-count payload,
not a Plotly figure, and client-side JavaScript builds the Mon–Sun grid.
A per-day Plotly spec for a multi-year repository is far larger than the
counts it encodes.

Everything written into a `<script>` block has `</` escaped to `<\/`.
Without it, a contributor whose name contains `</script>` closes the
block and executes the remainder as markup. `_sanitise_chart_label`
strips HTML tags from labels for the same reason. Jinja autoescaping is
on (`select_autoescape(["html", "j2"])`), but it does not apply inside a
JSON script block — that is why the escaping is explicit.

`_to_json` strips `paper_bgcolor`, `plot_bgcolor`, and `font.color`
from the serialised layout. Theme colours are injected client-side via
`Plotly.relayout()` when the toggle flips, so the charts recolour
without a re-render.

`_PLOTLY_JS_BUNDLE` is read once at module import. `get_plotlyjs()`
reads ~3.5 MB from disk per call; caching it took the e2e suite from
roughly forty minutes to two.

---

## Configuration

`ReportConfig` (Pydantic) holds `repo_path`, `output_path`, `title`,
`branch`, `since`, `until`, `exclude_authors`, `min_commits`,
`ranking_enabled`, `ranking_weights`, `output_format`
(`"html" | "json" | "csv"`). A validator enforces `since < until`.

`RankingWeights` holds `commits=0.30`, `lines=0.25`, `consistency=0.25`,
`recency=0.20`, each in `[0, 1]`, with a validator enforcing that they
sum to 1.0 within `1e-6`.

`load_config_from_toml` reads via stdlib `tomllib` and flattens
`[report]`, `[filters]`, and `[ranking]` into a `ReportConfigKwargs`
`TypedDict`.

**Precedence: an explicitly provided CLI flag always beats the config
file.** `min_commits` carries a `None` sentinel for this reason —
without it, `--min-commits 1` is indistinguishable from "not provided",
and a config file setting `min_commits = 2` silently wins over an
explicit flag.

---

## Ranking

Contributors are scored on four components, min-max normalised, combined
by weighted sum, then converted to percentiles and tiers.

Consistency is passed through `_normalise_scores` unchanged; it is
already in `[0, 1]`. When max equals min, every value resolves to 1.0.

Recency bins commits by ISO calendar week, weights the anchor week 1.0,
and decays each earlier week by `_RECENCY_DECAY = 0.85`.

Percentiles use `bisect.bisect_left` for lower-bound semantics, so tied
scores get identical percentiles — see
[ADR-0003](adr/0003-bisect-left-for-percentile-ties.md).

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

The `-1.0` entry is an exhaustive fallback, so no valid percentile can
fail to match. `assign_tier` raises `AssertionError` if none matches —
unreachable in production, and a loud signal that `_TIER_BOUNDARIES`
was misconfigured. It replaced a silent `return "Recruit"` default that
would have hidden exactly that.

> **On interpreting these numbers.** Ranking measures commit and line
> volume. It does not measure contribution, and the professional
> consensus — DORA and SPACE both state this explicitly — is against
> using such metrics for individual assessment. The rankings exist to
> show *shape of participation*, not to grade people. See the User
> Guide for the caveat that ships to users.

---

## Testing

| Tier | Location | Rule |
|---|---|---|
| Unit | `tests/unit/` | No I/O, no filesystem, no subprocess. Inputs constructed directly. |
| Integration | `tests/integration/` | Real Git repositories built by fixtures via `subprocess`. |
| E2E | `tests/e2e/` | Full CLI invocation through Typer's `CliRunner`. |

The suite runs under `pytest-xdist` (`-n auto`). Fixtures that build
repositories are module-scoped and use `tmp_path_factory`, not
`tmp_path`, which is per-test and not worker-safe. Coverage gate is 90%.

Several tests exist specifically to stop a guarantee eroding, and are
worth knowing about before you change what they cover:

- **Offline moat** — no `<link>`, `<script>`, or `<img>` in the output references a remote host.
- **Layering** — no framework import crosses the boundaries above.
- **Contrast** — WCAG AA ratios computed from the template's own CSS custom properties, so a palette edit is checked without anyone updating a fixture.
- **Packaging** — the `py.typed` marker is present in both wheel and sdist.
- **Workflow pins** — every GitHub Action is pinned to a commit SHA with a comment naming a precise version.

---

## Toolchain

| Tool | Role |
|---|---|
| Poetry | Dependencies, virtualenv, build, publish |
| ruff | Lint (E,W,F,I,C,B,UP,N,SIM,D,RUF) and format — the sole formatter |
| mypy `strict` | Type checking |
| pytest + xdist + cov | Testing, parallelism, coverage |
| pre-commit (`repo: local`) | ruff and mypy, run inside the Poetry venv so versions cannot diverge from CI |
| GitHub Actions | CI across Python 3.11–3.14; publish on `v*` tag |
| PyPI OIDC trusted publisher | No stored credentials; PEP 740 attestations |

`make ci` runs the same gates CI does. Run it before opening a pull
request.
