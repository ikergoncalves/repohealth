# repohealth

**One command to see how healthy a Git repository really is.**

[![PyPI](https://img.shields.io/pypi/v/repohealth)](https://pypi.org/project/repohealth/)
[![Python versions](https://img.shields.io/pypi/pyversions/repohealth)](https://pypi.org/project/repohealth/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/ikergoncalves/repohealth/ci.yml)](https://github.com/ikergoncalves/repohealth/actions)

![Demo: repohealth scanning a repository and printing its health report](docs/demo.gif)

## Why repohealth?

Static analysis tells you how your code **is**; the Git history tells you
how it **changes**. Each one alone misses half the picture: a complex file
nobody touches is rarely a problem, and a frequently changed file that is
simple is usually fine. repohealth crosses both to surface **risk files**
— the ones that are hot *and* complex — alongside the bus factor of your
team's knowledge and the source files that have no tests at all. It runs
100% locally on any Git repository, with no server, no database and no
configuration.

## Features

- **`report`** — consolidated 0-100 health score with letter grade, risk
  files, and JSON/Markdown/HTML export; usable as a CI quality gate.
- **`scan`** — tracked files grouped by language, with line counts.
- **`complexity`** — cyclomatic complexity ranks (A-F) for every Python
  file, with a threshold gate for CI.
- **`hotspots`** — the files changed most often across the history.
- **`busfactor`** — the fewest authors covering half of all changes.
- **`untested`** — Python source files without a matching test file.

## Installation

```bash
pipx install repohealth   # recommended for CLIs: isolated environment
# or
pip install repohealth
```

Requires Python 3.10+ and Git.

## Quick start

Point it at any local Git repository:

```console
$ repohealth report .
┌────── repohealth ──────┐
│ repohealth             │
│ E:\projetos\repohealth │
└────────────────────────┘
┌─ Health score ─┐
│ 84.2 / 100     │
│ Grade B        │
└────────────────┘
                            Health components
┌────────────┬───────┬────────┬──────────────────────────────────────────┐
│ Component  │ Score │ Weight │ Detail                                   │
├────────────┼───────┼────────┼──────────────────────────────────────────┤
│ Complexity │  94.1 │    30% │ 1 of 17 files rank C or worse            │
│ Coverage   │ 100.0 │    25% │ 7 of 7 source files have a matching test │
│ Bus factor │  30.0 │    20% │ bus factor 1                             │
│ Churn risk │ 100.0 │    25% │ 0 of 1 hot files are also complex        │
└────────────┴───────┴────────┴──────────────────────────────────────────┘
Run repohealth report --format html --output report.html for the full report
```

## Commands

### `repohealth scan [PATH]`

Lists the files tracked by Git, groups them by language and shows file
counts, line counts and each language's share of the codebase. `PATH`
defaults to the current directory (as it does for every command).

```bash
repohealth scan path/to/repo
```

### `repohealth complexity [PATH]`

Analyzes the cyclomatic complexity of every tracked Python file using
[radon](https://radon.readthedocs.io/) and shows, per file, the number of
functions, average and maximum complexity, and a rank from A (simple) to F
(very complex).

Options:

- `--top N` — show only the N most complex files (default: 10).
- `--all` — show all files, ignoring `--top`.
- `--threshold RANK` — only list files ranked at or worse than `RANK`
  (A-F). If any file matches, the command exits with code **2**, which
  makes it easy to fail a CI job when complexity regresses:

  ```bash
  repohealth complexity . --threshold C || echo "too complex!"
  ```

Python files that cannot be parsed (syntax errors, non-UTF-8 encoding) are
reported as skipped and do not abort the analysis.

### `repohealth hotspots [PATH]`

Mines the Git history with [PyDriller](https://pydriller.readthedocs.io/)
and lists the files changed most often (churn), with the number of
distinct authors and the date of the last change. Renames carry their
history over to the new path, deleted files are excluded and merge
commits are skipped.

Options:

- `--top N` — show only the N most changed files (default: 10).
- `--all` — show all files, ignoring `--top`.
- `--since YYYY-MM-DD` — only analyze commits from this date onwards.
- `--max-commits N` — only analyze the N most recent commits.

### `repohealth busfactor [PATH]`

Computes the repository bus factor: the smallest number of authors who
together account for at least 50% of all file changes in the history. A
bus factor of 1 means the knowledge is concentrated in a single author
and is highlighted as a risk.

Options:

- `--since YYYY-MM-DD` — only analyze commits from this date onwards.
- `--max-commits N` — only analyze the N most recent commits.

Both history commands print `no history to analyze` and exit successfully
when the repository has no commits (or none match the filters).

### `repohealth untested [PATH]`

Lists the tracked Python source files that have no matching test file.

Options:

- `--all` — also show the source files that do have a matching test.

A source file `foo.py` counts as **tested** when the repository tracks a
test file following the common Python naming conventions:

- `tests/**/test_foo.py` or `tests/**/foo_test.py` — any depth inside a
  `tests/` directory;
- `test_foo.py` or `foo_test.py` in the same directory as the source.

Test files themselves (`test_*.py`, `*_test.py`, `conftest.py`),
`__init__.py`, `__main__.py`, `setup.py` and non-Python files are
excluded from the analysis.

The pairing is done by file **stem**, not by full path: when two source
files share the same name (say, two `utils.py` in different packages), a
single `test_utils.py` marks both as tested. Those matches are shown as
`tested*` — the asterisk flags a possible false positive.

### `repohealth report [PATH]`

Runs all four analyses and consolidates them into a single health score
from 0 to 100 with a letter grade (A-F), plus the list of risk files
(see [How it works](#how-it-works)).

Options:

- `--format terminal|json|markdown|html` — output format (default:
  `terminal`). The non-terminal formats print raw content to stdout so
  they can be piped or redirected.
- `--output FILE` — write the report to a file instead of stdout
  (`json`/`markdown`/`html` only; the `terminal` format cannot be
  written to a file and exits with code 1).
- `--since YYYY-MM-DD` / `--max-commits N` — passed through to the
  history analysis.
- `--min-score N` — exit with code **2** when the health score is below
  `N` (0-100).

## Configuration

repohealth reads an optional configuration from the analyzed repository
(the `PATH` argument, not the current directory). Two locations are
supported — the first one found wins:

1. `.repohealth.toml` at the repository root (the file's root table is
   the configuration);
2. the `[tool.repohealth]` section of `pyproject.toml`.

Without either, the built-in defaults apply. Any command accepts
`--no-config` to skip discovery and use the defaults — handy when
debugging a broken configuration file.

A complete `.repohealth.toml`:

```toml
# Gitignore-style patterns; matching files are invisible to every
# analysis: scan, complexity, hotspots, ownership, bus factor and
# test pairing.
exclude = ["docs/", "*.gen.py", "src/legacy/**"]

# Fail `report` with exit code 2 below this score (CI gate).
min_score = 70

# Fail `complexity` with exit code 2 at or worse than this rank.
complexity_threshold = "C"

# Component weights for the health score. All-or-nothing: give all
# four keys or omit the table entirely. Must sum to 1.0.
[weights]
complexity = 0.30
coverage = 0.25
bus_factor = 0.20
churn_risk = 0.25
```

| Key                    | Default              | Meaning                                            |
| ---------------------- | -------------------- | -------------------------------------------------- |
| `exclude`              | `[]`                 | Gitignore-style patterns removed from all analyses |
| `min_score`            | none                 | Default `--min-score` gate for `report` (0-100)    |
| `complexity_threshold` | none                 | Default `--threshold` gate for `complexity` (A-F)  |
| `weights`              | `0.30/0.25/0.20/0.25` | Score weights: complexity/coverage/bus_factor/churn_risk |

Precedence is **defaults < config file < explicit CLI flag**:
`--min-score` and `--threshold` on the command line override the file;
weights and excludes come only from the file (a `--exclude` flag is a
possible future addition). Unknown keys and invalid values fail fast
with a clear error instead of being silently ignored.

`report --format json` includes a `config` block with the effective
values used — the weights, the exclude patterns and their `source`
(`".repohealth.toml"`, `"pyproject.toml"` or `"defaults"`) — so a score
is always traceable to the configuration that produced it.

## Using in CI

`report --min-score` exits with code 2 when the score drops below the
bar, failing the job:

```yaml
- name: Repository health gate
  run: |
    pip install repohealth
    repohealth report . --min-score 70
```

To keep the full report as a build artifact:

```yaml
- name: Export health report
  run: repohealth report . --format json --output health.json
- uses: actions/upload-artifact@v4
  with:
    name: health-report
    path: health.json
```

## How it works

**Complexity** — every tracked Python file is parsed with
[radon](https://radon.readthedocs.io/) (AST-based), which computes the
cyclomatic complexity of each function and derives a per-file A-F rank
from the average.

**History** — [PyDriller](https://pydriller.readthedocs.io/) walks the
commit history (skipping merge commits, following renames) to count how
often each file changes and how the changes are distributed across
authors. That yields the hotspots and the bus factor.

**Test pairing** — a naming-convention heuristic matches each source
file to a test file (`test_foo.py` / `foo_test.py`). Matching is done by
file stem, so two sources with the same name can be satisfied by a single
test file — those matches are flagged as ambiguous.

**Score** — the health score is a weighted sum of four components:

| Component  | Weight | What it measures                                   |
| ---------- | -----: | -------------------------------------------------- |
| Complexity |    30% | Share of Python files ranked A or B                |
| Coverage   |    25% | Share of source files with a matching test file    |
| Bus factor |    20% | Knowledge concentration (bus factor 1 is riskiest) |
| Churn risk |    25% | Share of hot files that are **not** also complex   |

The report also lists the **risk files**: files that are at the same time
*hot* (changed at least half as often as the most-changed Python file)
and *complex* (rank C or worse). Churn and complexity are each manageable
on their own — their intersection is where refactoring pays off the most.

## Limitations

- The test heuristic checks that a plausibly named test file **exists**;
  it is not real coverage measurement (use
  [pytest-cov](https://pytest-cov.readthedocs.io/) for that).
- Complexity analysis covers Python files only.
- History analysis skips merge commits; renames are tracked, but heavily
  rewritten files may count as new.

## Roadmap

- Complexity support for more languages.
- `--exclude` flag to complement the config file patterns.
- Health score badge for READMEs.
- Trend view: score evolution across the history.

## Contributing

PRs are welcome. Before opening one, please run the test suite and the
linters:

```bash
poetry install
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
```

## License

[MIT](LICENSE)
