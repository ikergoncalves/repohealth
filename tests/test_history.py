"""Tests for :mod:`repohealth.core.history`."""

from datetime import datetime
from pathlib import Path

import pytest
from git import Actor, Repo

from repohealth.core.history import FileChurn, FileOwnership, HistoryReport, analyze_history

_AUTHOR_A = Actor("Alice Dev", "alice@example.com")
_AUTHOR_B = Actor("Bob Dev", "bob@example.com")

_SHARED_SOURCE = "def shared():\n    return 42\n\n\ndef helper():\n    return 'stable content'\n"


def _write(root: Path, name: str, content: str) -> None:
    (root / name).write_text(content, encoding="utf-8")


def _commit(repo: Repo, message: str, author: Actor, day: int, add: list[str] | None = None):
    """Commit staged changes with a deterministic date in January 2024."""
    if add:
        repo.index.add(add)
    date = f"2024-01-{day:02d}T12:00:00"
    return repo.index.commit(
        message, author=author, committer=author, author_date=date, commit_date=date
    )


@pytest.fixture
def multi_author_repo(tmp_path: Path) -> Path:
    """Repository with two authors, a rename and a file deleted mid-history.

    History (one commit per day of January 2024):
    day 1  A: adds file_a.py and file_d.py
    day 2  A: modifies file_a.py
    day 3  A: modifies file_a.py
    day 4  B: modifies file_a.py
    day 5  B: adds file_b.py
    day 6  A: renames file_b.py -> file_c.py
    day 7  A: deletes file_d.py
    """
    with Repo.init(tmp_path) as repo:
        _write(tmp_path, "file_a.py", "VERSION = 1\n")
        _write(tmp_path, "file_d.py", "DOOMED = True\n")
        _commit(repo, "add file_a and file_d", _AUTHOR_A, day=1, add=["file_a.py", "file_d.py"])

        _write(tmp_path, "file_a.py", "VERSION = 2\n")
        _commit(repo, "bump file_a to v2", _AUTHOR_A, day=2, add=["file_a.py"])

        _write(tmp_path, "file_a.py", "VERSION = 3\n")
        _commit(repo, "bump file_a to v3", _AUTHOR_A, day=3, add=["file_a.py"])

        _write(tmp_path, "file_a.py", "VERSION = 4\n")
        _commit(repo, "bump file_a to v4", _AUTHOR_B, day=4, add=["file_a.py"])

        _write(tmp_path, "file_b.py", _SHARED_SOURCE)
        _commit(repo, "add file_b", _AUTHOR_B, day=5, add=["file_b.py"])

        (tmp_path / "file_b.py").rename(tmp_path / "file_c.py")
        repo.index.remove(["file_b.py"])
        _commit(repo, "rename file_b to file_c", _AUTHOR_A, day=6, add=["file_c.py"])

        repo.index.remove(["file_d.py"], working_tree=True)
        _commit(repo, "delete file_d", _AUTHOR_A, day=7)
    return tmp_path


def _churn_by_path(report: HistoryReport) -> dict[str, FileChurn]:
    return {churn.path.as_posix(): churn for churn in report.hotspots}


def _ownership_by_path(report: HistoryReport) -> dict[str, FileOwnership]:
    return {ownership.path.as_posix(): ownership for ownership in report.ownership}


def test_change_count_sums_commits_from_all_authors(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo)

    churn = _churn_by_path(report)["file_a.py"]

    assert report.analyzed_commit_count == 7
    assert churn.change_count == 4
    assert churn.author_count == 2
    assert churn.last_modified.strftime("%Y-%m-%d") == "2024-01-04"


def test_rename_migrates_churn_to_new_path(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo)

    churn = _churn_by_path(report)

    assert "file_b.py" not in churn
    assert churn["file_c.py"].change_count == 2  # creation as file_b + rename commit
    assert churn["file_c.py"].author_count == 2


def test_deleted_file_is_not_reported(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo)

    assert "file_d.py" not in _churn_by_path(report)
    assert "file_d.py" not in _ownership_by_path(report)


def test_hotspots_sorted_by_change_count_desc(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo)

    change_counts = [churn.change_count for churn in report.hotspots]

    assert change_counts == sorted(change_counts, reverse=True)
    assert report.hotspots[0].path == Path("file_a.py")


def test_bus_factor_one_when_a_single_author_dominates(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo)

    # A: 2 changes (day 1) + 1 (day 2) + 1 (day 3) + 1 (rename) + 1 (delete) = 6 of 8.
    assert report.total_changes == 8
    assert report.bus_factor == 1
    assert report.bus_factor_authors == ("Alice Dev",)
    assert report.author_totals == (("Alice Dev", 6), ("Bob Dev", 2))


def test_ownership_of_file_a(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo)

    ownership = _ownership_by_path(report)["file_a.py"]

    assert ownership.total_changes == 4
    assert ownership.top_author == "Alice Dev"
    assert ownership.top_author_share == pytest.approx(0.75)
    assert ownership.authors == (("Alice Dev", 3), ("Bob Dev", 1))


def test_since_excludes_older_commits(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo, since=datetime(2024, 1, 4))

    churn = _churn_by_path(report)

    assert report.analyzed_commit_count == 4  # days 4-7
    assert churn["file_a.py"].change_count == 1
    assert churn["file_a.py"].author_count == 1


def test_max_commits_keeps_only_the_most_recent(multi_author_repo: Path) -> None:
    report = analyze_history(multi_author_repo, max_commits=2)

    churn = _churn_by_path(report)

    assert report.analyzed_commit_count == 2  # rename (day 6) + delete (day 7)
    assert "file_a.py" not in churn
    assert churn["file_c.py"].change_count == 1


def test_empty_repository_returns_empty_report(tmp_path: Path) -> None:
    with Repo.init(tmp_path):
        pass

    report = analyze_history(tmp_path)

    assert report.analyzed_commit_count == 0
    assert report.hotspots == ()
    assert report.ownership == ()
    assert report.bus_factor == 0
    assert report.bus_factor_authors == ()
    assert report.total_changes == 0


def test_merge_commits_are_skipped(tmp_path: Path) -> None:
    with Repo.init(tmp_path) as repo:
        with repo.config_writer() as config:
            config.set_value("user", "name", _AUTHOR_A.name)
            config.set_value("user", "email", _AUTHOR_A.email)

        _write(tmp_path, "base.py", "BASE = True\n")
        _commit(repo, "add base", _AUTHOR_A, day=1, add=["base.py"])
        default_branch = repo.active_branch.name

        repo.git.checkout("-b", "feature")
        _write(tmp_path, "feat.py", "FEATURE = True\n")
        _commit(repo, "add feat", _AUTHOR_B, day=2, add=["feat.py"])

        repo.git.checkout(default_branch)
        _write(tmp_path, "main_only.py", "MAIN = True\n")
        _commit(repo, "add main_only", _AUTHOR_A, day=3, add=["main_only.py"])

        repo.git.merge("feature", m="merge feature")

    report = analyze_history(tmp_path)

    churn = _churn_by_path(report)

    assert report.analyzed_commit_count == 3  # merge commit skipped
    assert churn["feat.py"].change_count == 1
    assert report.total_changes == 3
