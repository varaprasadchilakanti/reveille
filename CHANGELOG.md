# Changelog

All notable changes to Reveille are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning 2.0](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/varaprasadchilakanti/reveille/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/varaprasadchilakanti/reveille/releases/tag/v0.1.0
