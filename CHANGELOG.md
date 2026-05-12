# Changelog

All notable changes to Reveille are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning 2.0](https://semver.org/).

---

## [Unreleased]

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

[Unreleased]: https://github.com/varaprasadchilakanti/reveille/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.4.1
[0.4.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.4.0
[0.3.3]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.3.3
[0.3.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.3.0
[0.2.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.2.0
[0.1.1]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.1.1
[0.1.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.1.0
