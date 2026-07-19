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

`repohealth scan` lists the files tracked by Git, groups them by language and
shows file counts, line counts and each language's share of the codebase.
