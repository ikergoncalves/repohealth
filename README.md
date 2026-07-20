# repohealth

CLI tool that analyzes any Git repository's health.

![Status: early development](https://img.shields.io/badge/status-early%20development-orange)

> **Note:** repohealth is in early development. Commands, output and APIs may
> change at any time.

## Installation (development)

Requires Python >= 3.10 and [Poetry](https://python-poetry.org/):

```bash
git clone <repo-url>
cd repohealth
poetry install
```

## Usage

```bash
# Scan the current directory (must be a Git repository)
poetry run repohealth scan

# Scan a specific repository
poetry run repohealth scan path/to/repo

# Show the installed version
poetry run repohealth --version
```

## Commands

### `repohealth scan [PATH]`

Lists the files tracked by Git, groups them by language and shows file
counts, line counts and each language's share of the codebase. `PATH`
defaults to the current directory.

```bash
poetry run repohealth scan path/to/repo
```

### `repohealth complexity [PATH]`

Analyzes the cyclomatic complexity of every tracked Python file using
[radon](https://radon.readthedocs.io/) and shows, per file, the number of
functions, average and maximum complexity, and a rank from A (simple) to F
(very complex). `PATH` defaults to the current directory.

```bash
poetry run repohealth complexity path/to/repo
```

Options:

- `--top N` — show only the N most complex files (default: 10).
- `--all` — show all files, ignoring `--top`.
- `--threshold RANK` — only list files ranked at or worse than `RANK`
  (A–F). If any file matches, the command exits with code **2**, which
  makes it easy to fail a CI job when complexity regresses:

  ```bash
  poetry run repohealth complexity . --threshold C || echo "too complex!"
  ```

Python files that cannot be parsed (syntax errors, non-UTF-8 encoding) are
reported as skipped and do not abort the analysis.

### `repohealth hotspots [PATH]`

Mines the Git history with [PyDriller](https://pydriller.readthedocs.io/)
and lists the files changed most often (churn), with the number of
distinct authors and the date of the last change. Renames carry their
history over to the new path, deleted files are excluded and merge
commits are skipped. `PATH` defaults to the current directory.

```bash
poetry run repohealth hotspots path/to/repo
```

Options:

- `--top N` — show only the N most changed files (default: 10).
- `--all` — show all files, ignoring `--top`.
- `--since YYYY-MM-DD` — only analyze commits from this date onwards.
- `--max-commits N` — only analyze the N most recent commits.

### `repohealth busfactor [PATH]`

Computes the repository bus factor: the smallest number of authors who
together account for at least 50% of all file changes in the history. A
bus factor of 1 means the knowledge is concentrated in a single author
and is highlighted as a risk. `PATH` defaults to the current directory.

```bash
poetry run repohealth busfactor path/to/repo
```

Options:

- `--since YYYY-MM-DD` — only analyze commits from this date onwards.
- `--max-commits N` — only analyze the N most recent commits.

Both commands print `no history to analyze` and exit successfully when
the repository has no commits (or none match the filters).

### `repohealth untested [PATH]`

Lists the tracked Python source files that have no matching test file.
`PATH` defaults to the current directory.

```bash
poetry run repohealth untested path/to/repo
```

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

This is a **static heuristic**: it only checks that a plausibly named
test file exists, not that the code is actually executed by tests. It
points out structural gaps and does not replace real coverage
measurement (e.g. [pytest-cov](https://pytest-cov.readthedocs.io/)).
The command always exits with code 0 when the analysis runs.

### `repohealth report [PATH]`

Runs all four analyses and consolidates them into a single **health
score** from 0 to 100 with a letter grade (A–F). The score is a
weighted sum of four components:

| Component  | Weight | What it measures                                    |
| ---------- | -----: | --------------------------------------------------- |
| Complexity |    30% | Share of Python files ranked A or B                 |
| Coverage   |    25% | Share of source files with a matching test file     |
| Bus factor |    20% | Knowledge concentration (bus factor 1 is riskiest)  |
| Churn risk |    25% | Share of hot files that are **not** also complex    |

The report also lists the **risk files**: files that are at the same
time *hot* (changed at least half as often as the most-changed Python
file) and *complex* (rank C or worse). Churn and complexity are each
manageable on their own — their intersection is where refactoring pays
off the most, and that is the metric the other commands cannot show
individually.

```bash
# Rich summary in the terminal
poetry run repohealth report

# Full report as JSON, Markdown or HTML (raw content on stdout)
poetry run repohealth report --format json
poetry run repohealth report --format markdown

# Write a self-contained HTML page to a file
poetry run repohealth report --format html --output report.html
```

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
  `N` (0–100). This makes `report` usable as a CI quality gate:

  ```bash
  # Fail the pipeline when the repository health drops below 70
  poetry run repohealth report . --min-score 70
  ```
