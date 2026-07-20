"""Tests for :mod:`repohealth.cli` using Typer's CliRunner."""

import json
from pathlib import Path

import pytest
from git import Actor, Repo
from typer.testing import CliRunner

from repohealth import __version__
from repohealth.cli import app

runner = CliRunner()

_AUTHOR_A = Actor("Alice Dev", "alice@example.com")
_AUTHOR_B = Actor("Bob Dev", "bob@example.com")


def _complex_source(marker: int) -> str:
    """A module whose single function has cyclomatic complexity 11 (rank C)."""
    branches = "\n".join(f"    if value == {i}:\n        return {i}" for i in range(10))
    return f"def dispatch(value):\n{branches}\n    return {marker}\n"


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Repo, message: str, author: Actor, day: int, add: list[str]) -> None:
    """Commit staged changes with a deterministic date in January 2024."""
    repo.index.add(add)
    date = f"2024-01-{day:02d}T12:00:00"
    repo.index.commit(message, author=author, committer=author, author_date=date, commit_date=date)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Git repository with history, a complex untested file and a tested one.

    - ``engine.py``  — complex (rank C), no matching test, modified twice.
    - ``simple.py``  — simple (rank A), paired with ``tests/test_simple.py``.
    - 3 commits: Alice owns 4 of 5 file changes, so the bus factor is 1.
    """
    root = tmp_path_factory.mktemp("cli_repo")
    with Repo.init(root) as git_repo:
        _write(root, "engine.py", _complex_source(0))
        _write(root, "simple.py", "VERSION = 1\n")
        _write(root, "tests/test_simple.py", "def test_simple():\n    assert True\n")
        _commit(
            git_repo,
            "add initial files",
            _AUTHOR_A,
            day=1,
            add=["engine.py", "simple.py", "tests/test_simple.py"],
        )
        for day, author in ((2, _AUTHOR_A), (3, _AUTHOR_B)):
            _write(root, "engine.py", _complex_source(day))
            _commit(git_repo, f"tweak engine day {day}", author, day=day, add=["engine.py"])
    return root


@pytest.fixture(scope="module")
def empty_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Git repository without any commit."""
    root = tmp_path_factory.mktemp("empty_repo")
    with Repo.init(root):
        pass
    return root


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"repohealth {__version__}" in result.output


def test_scan_valid_repo_lists_languages(repo: Path) -> None:
    result = runner.invoke(app, ["scan", str(repo)])

    assert result.exit_code == 0
    assert repo.name in result.output
    assert "Python" in result.output
    assert "tracked files" in result.output


def test_scan_non_git_directory_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error:" in result.output


def test_complexity_ranks_python_files(repo: Path) -> None:
    result = runner.invoke(app, ["complexity", str(repo)])

    assert result.exit_code == 0
    assert "engine.py" in result.output
    assert " C " in result.output  # rank column for engine.py


def test_complexity_threshold_violation_exits_2(repo: Path) -> None:
    result = runner.invoke(app, ["complexity", str(repo), "--threshold", "A"])

    assert result.exit_code == 2
    assert "threshold exceeded" in result.output


def test_complexity_threshold_without_matches_reports_success(repo: Path) -> None:
    result = runner.invoke(app, ["complexity", str(repo), "--threshold", "F"])

    assert result.exit_code == 0
    assert "No files at or worse than rank F" in result.output


def test_complexity_invalid_threshold_is_rejected(repo: Path) -> None:
    result = runner.invoke(app, ["complexity", str(repo), "--threshold", "X"])

    assert result.exit_code != 0
    assert "Threshold must be a single rank letter" in result.output


def test_complexity_all_shows_every_file(repo: Path) -> None:
    result = runner.invoke(app, ["complexity", str(repo), "--all", "--top", "1"])

    assert result.exit_code == 0
    assert "engine.py" in result.output
    assert "simple.py" in result.output


def test_complexity_warns_about_unparsable_files(tmp_path: Path) -> None:
    with Repo.init(tmp_path) as git_repo:
        _write(tmp_path, "good.py", "VALUE = 1\n")
        _write(tmp_path, "broken.py", "def broken(:\n")
        _commit(git_repo, "add files", _AUTHOR_A, day=1, add=["good.py", "broken.py"])

    result = runner.invoke(app, ["complexity", str(tmp_path)])

    assert result.exit_code == 0
    assert "skipped unparsable" in result.output
    assert "broken.py" in result.output


def test_hotspots_reports_commit_count(repo: Path) -> None:
    result = runner.invoke(app, ["hotspots", str(repo)])

    assert result.exit_code == 0
    assert "3" in result.output
    assert "commit(s)" in result.output


def test_hotspots_invalid_since_date_fails(repo: Path) -> None:
    result = runner.invoke(app, ["hotspots", str(repo), "--since", "not-a-date"])

    assert result.exit_code == 1
    assert "Error:" in result.output


def test_hotspots_empty_repo_reports_no_history(empty_repo: Path) -> None:
    result = runner.invoke(app, ["hotspots", str(empty_repo)])

    assert result.exit_code == 0
    assert "no history to analyze" in result.output


def test_busfactor_reports_bus_factor(repo: Path) -> None:
    result = runner.invoke(app, ["busfactor", str(repo)])

    assert result.exit_code == 0
    assert "Bus factor" in result.output


def test_untested_lists_missing_files(repo: Path) -> None:
    result = runner.invoke(app, ["untested", str(repo)])

    assert result.exit_code == 0
    assert "engine.py" in result.output
    assert "missing" in result.output


def test_untested_all_marks_stem_only_matches(tmp_path: Path) -> None:
    with Repo.init(tmp_path) as git_repo:
        _write(tmp_path, "pkg_a/utils.py", "A = 1\n")
        _write(tmp_path, "pkg_b/utils.py", "B = 2\n")
        _write(tmp_path, "tests/test_utils.py", "def test_utils():\n    assert True\n")
        _commit(
            git_repo,
            "add files",
            _AUTHOR_A,
            day=1,
            add=["pkg_a/utils.py", "pkg_b/utils.py", "tests/test_utils.py"],
        )

    result = runner.invoke(app, ["untested", str(tmp_path), "--all"])

    assert result.exit_code == 0
    assert "tested*" in result.output
    assert "matched by file stem only" in result.output


def test_untested_without_python_sources_reports_nothing_to_analyze(tmp_path: Path) -> None:
    with Repo.init(tmp_path) as git_repo:
        _write(tmp_path, "README.md", "# docs\n")
        _commit(git_repo, "add readme", _AUTHOR_A, day=1, add=["README.md"])

    result = runner.invoke(app, ["untested", str(tmp_path)])

    assert result.exit_code == 0
    assert "no Python source files to analyze" in result.output


def test_report_terminal_shows_health_score(repo: Path) -> None:
    result = runner.invoke(app, ["report", str(repo)])

    assert result.exit_code == 0
    assert "Health score" in result.output
    assert "Grade" in result.output


def test_report_json_is_parseable(repo: Path) -> None:
    result = runner.invoke(app, ["report", str(repo), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == __version__


def test_report_markdown_starts_with_title(repo: Path) -> None:
    result = runner.invoke(app, ["report", str(repo), "--format", "markdown"])

    assert result.exit_code == 0
    assert result.stdout.startswith("# repohealth")


def test_report_html_output_writes_file(repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "r.html"

    result = runner.invoke(app, ["report", str(repo), "--format", "html", "--output", str(target)])

    assert result.exit_code == 0
    assert target.exists()
    assert "<!DOCTYPE html>" in target.read_text(encoding="utf-8")


def test_report_terminal_format_rejects_output_file(repo: Path) -> None:
    result = runner.invoke(app, ["report", str(repo), "--output", "x"])

    assert result.exit_code == 1
    assert "Error:" in result.output


def test_report_min_score_gate_exits_2(repo: Path) -> None:
    result = runner.invoke(app, ["report", str(repo), "--min-score", "100"])

    assert result.exit_code == 2
    assert "below the required minimum" in result.output


def test_unknown_command_fails() -> None:
    result = runner.invoke(app, ["definitely-not-a-command"])

    assert result.exit_code != 0
