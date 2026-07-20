"""Tests for :mod:`repohealth.core.coverage_gaps`."""

from pathlib import Path

import pytest
from git import Actor, Repo

from repohealth.core.coverage_gaps import CoverageGapReport, SourceFileStatus, find_coverage_gaps

_AUTHOR = Actor("Test Author", "test@example.com")


def _commit_files(root: Path, files: list[str]) -> None:
    """Create the given files (with parents) and commit them all at once."""
    for name in files:
        file_path = root / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f"# {name}\n", encoding="utf-8")
    with Repo.init(root) as repo:
        repo.index.add(files)
        repo.index.commit("add project files", author=_AUTHOR, committer=_AUTHOR)


@pytest.fixture
def project_repo(tmp_path: Path) -> Path:
    """Repository with tested, untested, ambiguous and excluded files."""
    _commit_files(
        tmp_path,
        [
            "src/pkg/alpha.py",
            "src/pkg/beta.py",
            "src/pkg/gamma.py",
            "src/pkg/util/delta.py",
            "src/pkg/util/delta_test.py",
            "src/pkg/utils.py",
            "src/other/utils.py",
            "src/pkg/__init__.py",
            "tests/test_alpha.py",
            "tests/unit/beta_test.py",
            "tests/test_utils.py",
            "tests/conftest.py",
            "web/script.js",
        ],
    )
    return tmp_path


def _status_by_path(report: CoverageGapReport) -> dict[str, SourceFileStatus]:
    return {status.path.as_posix(): status for status in report.files}


def test_source_with_test_in_tests_dir_is_tested(project_repo: Path) -> None:
    status = _status_by_path(find_coverage_gaps(project_repo))["src/pkg/alpha.py"]

    assert status.has_test
    assert status.matched_tests == (Path("tests/test_alpha.py"),)
    assert not status.ambiguous


def test_suffix_convention_in_tests_subdirectory_is_tested(project_repo: Path) -> None:
    status = _status_by_path(find_coverage_gaps(project_repo))["src/pkg/beta.py"]

    assert status.has_test
    assert status.matched_tests == (Path("tests/unit/beta_test.py"),)
    assert not status.ambiguous


def test_source_without_test_is_missing(project_repo: Path) -> None:
    status = _status_by_path(find_coverage_gaps(project_repo))["src/pkg/gamma.py"]

    assert not status.has_test
    assert status.matched_tests == ()
    assert not status.ambiguous


def test_test_in_same_directory_pairs_the_source(project_repo: Path) -> None:
    status = _status_by_path(find_coverage_gaps(project_repo))["src/pkg/util/delta.py"]

    assert status.has_test
    assert status.matched_tests == (Path("src/pkg/util/delta_test.py"),)
    assert not status.ambiguous


def test_repeated_stem_marks_both_sources_as_ambiguous(project_repo: Path) -> None:
    statuses = _status_by_path(find_coverage_gaps(project_repo))

    for path in ("src/pkg/utils.py", "src/other/utils.py"):
        assert statuses[path].has_test
        assert statuses[path].matched_tests == (Path("tests/test_utils.py"),)
        assert statuses[path].ambiguous


def test_excluded_files_do_not_appear_in_the_report(project_repo: Path) -> None:
    paths = set(_status_by_path(find_coverage_gaps(project_repo)))

    assert paths == {
        "src/pkg/alpha.py",
        "src/pkg/beta.py",
        "src/pkg/gamma.py",
        "src/pkg/util/delta.py",
        "src/pkg/utils.py",
        "src/other/utils.py",
    }


def test_untested_files_come_first(project_repo: Path) -> None:
    report = find_coverage_gaps(project_repo)

    assert report.files[0].path == Path("src/pkg/gamma.py")
    assert all(status.has_test for status in report.files[1:])


def test_counts_and_coverage_ratio(project_repo: Path) -> None:
    report = find_coverage_gaps(project_repo)

    assert report.source_file_count == 6
    assert report.tested_count == 5
    assert report.untested_count == 1
    assert report.coverage_ratio == pytest.approx(5 / 6)


def test_repository_without_python_sources(tmp_path: Path) -> None:
    _commit_files(tmp_path, ["web/script.js", "README.md"])

    report = find_coverage_gaps(tmp_path)

    assert report.files == ()
    assert report.source_file_count == 0
    assert report.tested_count == 0
    assert report.untested_count == 0
    assert report.coverage_ratio == 1.0
