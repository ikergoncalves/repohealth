# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Configuration file support: `.repohealth.toml` at the repository root
  or a `[tool.repohealth]` section in `pyproject.toml` (the first found
  wins), with fail-fast validation of unknown keys and invalid values.
- `exclude` configuration key: gitignore-style patterns removed from
  every analysis — scan, complexity, hotspots, ownership, bus factor
  and test pairing.
- `weights` configuration table to customize the health score component
  weights (all four keys, summing to 1.0).
- `min_score` and `complexity_threshold` configuration keys as file
  defaults for the `report --min-score` and `complexity --threshold`
  gates; explicit CLI flags still win.
- `--no-config` flag on every command to ignore configuration files and
  use the built-in defaults.
- `config` block in `report --format json` exposing the effective
  weights, exclude patterns and configuration source.

## [0.1.0] - 2026-07-20

### Added

- `scan` command: list tracked files grouped by language, with file, line
  and percentage counts.
- `complexity` command: cyclomatic complexity of tracked Python files via
  radon, with A-F ranks, `--top`/`--all` filters and a `--threshold` CI
  gate (exit code 2 on violation).
- `hotspots` command: most frequently changed files mined from the Git
  history via PyDriller, with `--top`/`--all`/`--since`/`--max-commits`.
- `busfactor` command: fewest authors covering half of all file changes,
  with a warning when the bus factor is 1.
- `untested` command: tracked Python source files without a matching test
  file, using a naming-convention heuristic.
- `report` command: consolidated health report with a weighted 0-100
  score, letter grade, risk files (hot and complex), JSON/Markdown/HTML
  exporters (`--format`, `--output`) and a `--min-score` CI gate (exit
  code 2 below the minimum).
- `--version` flag.
