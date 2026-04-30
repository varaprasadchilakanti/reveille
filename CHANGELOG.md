# Changelog

All notable changes to Reveille are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning 2.0](https://semver.org/).

## [Unreleased]

### Added
- Project README covering installation, quickstart, CLI reference,
  contributor ranking system, configuration schema, and contribution guidelines.
- pyproject.toml with full Poetry configuration and tool settings
  for ruff, mypy, pytest, and coverage.
- poetry.lock for reproducible dependency resolution.
- .gitignore scoped to a Python CLI project using Poetry.
- Domain models: Commit, ContributorStats, RankedContributor,
  RepositoryMetadata, ReportData.
- Domain exception hierarchy under reveille.exceptions.
- Configuration models: ReportConfig, RankingWeights with validation.
- Ranking engine interface with tier boundary definitions.
- GitReader adapter interface.
- Renderer adapter interface.
- Typer CLI with generate, validate, and version commands.
- Pytest fixture stubs in tests/conftest.py.
- GitHub Actions CI workflow (lint, typecheck, test in parallel).
- Makefile with standard development targets.
- MIT licence.

[Unreleased]: https://github.com/varaprasadchilakanti/reveille/compare/HEAD

### Changed
- Tier designation strings updated to a consistent NATO-aligned military
  rank progression: Private, Corporal, Sergeant, Lieutenant, Captain,
  Major, Commander. The previous set mixed military and professional
  title conventions inconsistently. Commander is retained at tier VII.
