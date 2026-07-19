"""Tests for :mod:`repohealth.core.repo_scanner`."""

from pathlib import Path

import pytest
from git import Actor, Repo

from repohealth.core.repo_scanner import (
    NotAGitRepositoryError,
    classify_language,
    count_lines,
    list_tracked_files,
    open_repository,
    scan_repository,
)

_COMMITTER = Actor("Test User", "test@example.com")

_TRACKED_TEXT_FILES = {
    "main.py": "import os\n\nprint(os.name)\n",  # 3 lines -> Python
    "app.js": "const x = 1;\nconsole.log(x);\n",  # 2 lines -> JavaScript
    "notes.txt": "just one line\n",  # 1 line -> Other
}
_BINARY_FILE = "logo.bin"
_BINARY_CONTENT = b"\x89PNG\r\n\x1a\n\x00\xff\xfe\xba\xad"
_UNTRACKED_FILE = "untracked.py"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a Git repository with committed files plus one untracked file."""
    with Repo.init(tmp_path) as repo:
        for name, content in _TRACKED_TEXT_FILES.items():
            (tmp_path / name).write_text(content, encoding="utf-8")
        (tmp_path / _BINARY_FILE).write_bytes(_BINARY_CONTENT)
        repo.index.add([*_TRACKED_TEXT_FILES, _BINARY_FILE])
        repo.index.commit("initial commit", author=_COMMITTER, committer=_COMMITTER)
    (tmp_path / _UNTRACKED_FILE).write_text("print('untracked')\n", encoding="utf-8")
    return tmp_path


def test_scan_returns_only_tracked_files(git_repo: Path) -> None:
    report = scan_repository(git_repo)

    scanned = {stats.path.as_posix() for stats in report.files}

    assert scanned == set(_TRACKED_TEXT_FILES) | {_BINARY_FILE}
    assert _UNTRACKED_FILE not in scanned
    assert report.total_files == 4


def test_list_tracked_files_ignores_untracked(git_repo: Path) -> None:
    repo = open_repository(git_repo)
    try:
        tracked = {path.as_posix() for path in list_tracked_files(repo)}
    finally:
        repo.close()

    assert tracked == set(_TRACKED_TEXT_FILES) | {_BINARY_FILE}


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("script.py", "Python"),
        ("app.js", "JavaScript"),
        ("component.tsx", "TypeScript (React)"),
        ("Main.JAVA", "Java"),
        ("query.sql", "Other"),
        ("Makefile", "Other"),
    ],
)
def test_classify_language(filename: str, expected: str) -> None:
    assert classify_language(Path(filename)) == expected


def test_count_lines(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.py"
    file_path.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

    assert count_lines(file_path) == 3


def test_count_lines_returns_none_for_binary(tmp_path: Path) -> None:
    file_path = tmp_path / "blob.bin"
    file_path.write_bytes(_BINARY_CONTENT)

    assert count_lines(file_path) is None


def test_scan_aggregates_lines_by_language(git_repo: Path) -> None:
    report = scan_repository(git_repo)

    by_language = {stats.language: stats for stats in report.languages}

    assert by_language["Python"].line_count == 3
    assert by_language["JavaScript"].line_count == 2
    assert by_language["Other"].file_count == 2  # notes.txt + logo.bin
    assert by_language["Other"].line_count == 1  # the binary contributes no lines
    assert report.total_lines == 6
    assert [stats.language for stats in report.languages] == ["Python", "JavaScript", "Other"]
    assert sum(stats.percent_of_lines for stats in report.languages) == pytest.approx(100.0)


def test_scan_rejects_directory_without_git(tmp_path: Path) -> None:
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()

    with pytest.raises(NotAGitRepositoryError):
        scan_repository(plain_dir)


def test_scan_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepositoryError):
        scan_repository(tmp_path / "does-not-exist")


def test_binary_file_does_not_break_scan(git_repo: Path) -> None:
    report = scan_repository(git_repo)

    binary = next(stats for stats in report.files if stats.path.name == _BINARY_FILE)

    assert binary.language == "Other"
    assert binary.lines is None
