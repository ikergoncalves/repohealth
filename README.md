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
