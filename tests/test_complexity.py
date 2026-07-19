"""Tests for :mod:`repohealth.core.complexity`."""

from pathlib import Path

import pytest
from git import Actor, Repo

from repohealth.core.complexity import analyze_complexity, rank_for

_COMMITTER = Actor("Test User", "test@example.com")

_SIMPLE_PY = "simple.py"
_SIMPLE_SOURCE = "def choose(flag):\n    if flag:\n        return 1\n    else:\n        return 2\n"

_COMPLEX_PY = "gnarly.py"
_COMPLEX_SOURCE = (
    "def gnarly(items):\n"
    "    total = 0\n"
    "    for item in items:\n"
    "        if item > 10:\n"
    "            if item % 2 == 0:\n"
    "                total += item\n"
    "            elif item % 3 == 0:\n"
    "                total -= item\n"
    "            elif item % 5 == 0:\n"
    "                total *= 2\n"
    "        elif item > 5:\n"
    "            while total > 0:\n"
    "                total -= 1\n"
    "        elif item > 0:\n"
    "            total += 1\n"
    "    return total\n"
)

_BROKEN_PY = "broken.py"
_BROKEN_SOURCE = "def oops(:\n    return\n"

_EMPTY_PY = "empty.py"

_NON_PYTHON = "app.js"
_NON_PYTHON_SOURCE = "function f(x) { if (x) { return 1; } return 2; }\n"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a Git repository with committed Python and non-Python files."""
    files = {
        _SIMPLE_PY: _SIMPLE_SOURCE,
        _COMPLEX_PY: _COMPLEX_SOURCE,
        _BROKEN_PY: _BROKEN_SOURCE,
        _EMPTY_PY: "",
        _NON_PYTHON: _NON_PYTHON_SOURCE,
    }
    with Repo.init(tmp_path) as repo:
        for name, content in files.items():
            (tmp_path / name).write_text(content, encoding="utf-8")
        repo.index.add(list(files))
        repo.index.commit("initial commit", author=_COMMITTER, committer=_COMMITTER)
    return tmp_path


def test_simple_function_has_coherent_complexity_and_rank(git_repo: Path) -> None:
    report = analyze_complexity(git_repo)

    simple = next(file for file in report.files if file.path.name == _SIMPLE_PY)

    assert len(simple.functions) == 1
    assert simple.functions[0].name == "choose"
    assert simple.functions[0].complexity == 2  # one if/else branch
    assert simple.functions[0].rank == "A"
    assert simple.average_complexity == pytest.approx(2.0)
    assert simple.max_complexity == 2
    assert simple.rank == "A"


def test_files_sorted_by_max_complexity_desc(git_repo: Path) -> None:
    report = analyze_complexity(git_repo)

    paths = [file.path.name for file in report.files]

    assert paths.index(_COMPLEX_PY) < paths.index(_SIMPLE_PY)
    complex_file = next(file for file in report.files if file.path.name == _COMPLEX_PY)
    simple_file = next(file for file in report.files if file.path.name == _SIMPLE_PY)
    assert complex_file.max_complexity > simple_file.max_complexity


def test_syntax_error_file_is_skipped_without_breaking(git_repo: Path) -> None:
    report = analyze_complexity(git_repo)

    assert [path.name for path in report.skipped_files] == [_BROKEN_PY]
    assert _BROKEN_PY not in {file.path.name for file in report.files}


def test_empty_python_file_gets_rank_a(git_repo: Path) -> None:
    report = analyze_complexity(git_repo)

    empty = next(file for file in report.files if file.path.name == _EMPTY_PY)

    assert empty.functions == ()
    assert empty.average_complexity == 0.0
    assert empty.max_complexity == 0
    assert empty.rank == "A"


def test_non_python_files_are_ignored(git_repo: Path) -> None:
    report = analyze_complexity(git_repo)

    analyzed = {file.path.name for file in report.files}

    assert _NON_PYTHON not in analyzed
    assert _NON_PYTHON not in {path.name for path in report.skipped_files}


def test_analyzed_file_count_is_consistent(git_repo: Path) -> None:
    report = analyze_complexity(git_repo)

    assert report.analyzed_file_count == len(report.files) == 3
    assert len(report.skipped_files) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "A"), (1.0, "A"), (5.0, "A"), (6.0, "B"), (11.0, "C"), (41.0, "F")],
)
def test_rank_for(value: float, expected: str) -> None:
    assert rank_for(value) == expected
