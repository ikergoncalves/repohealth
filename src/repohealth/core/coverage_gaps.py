"""Detection of Python source files without a matching test file.

This module holds the pure, testable core of the ``repohealth untested``
command: it pairs the tracked Python source files with tracked test
files using common naming conventions of the Python ecosystem. The
pairing is a static heuristic based on file names only, not a substitute
for real coverage measurement.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from repohealth.core.repo_scanner import list_tracked_files, open_repository

EXCLUDED_SOURCE_NAMES = frozenset({"__init__.py", "__main__.py", "setup.py"})
TESTS_DIR_NAME = "tests"


@dataclass(frozen=True)
class SourceFileStatus:
    """Pairing result for a single Python source file.

    ``ambiguous`` is ``True`` when the test was matched purely by file
    stem while the same stem exists in more than one source file, so
    the match may be a false positive.
    """

    path: Path
    has_test: bool
    matched_tests: tuple[Path, ...]
    ambiguous: bool


@dataclass(frozen=True)
class CoverageGapReport:
    """Complete result of pairing the source files with test files.

    ``files`` is sorted with untested files first, then by path.
    ``coverage_ratio`` is ``tested_count / source_file_count`` in the
    0-1 range, defined as 1.0 when there are no source files.
    """

    repo_path: Path
    files: tuple[SourceFileStatus, ...]
    source_file_count: int
    tested_count: int
    untested_count: int
    coverage_ratio: float


def _is_test_file(path: Path) -> bool:
    """Whether a ``.py`` path follows a test-file naming convention."""
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test") or path.name == "conftest.py"


def _is_source_file(path: Path) -> bool:
    """Whether a tracked file is a Python source file subject to pairing."""
    if path.suffix != ".py" or path.name in EXCLUDED_SOURCE_NAMES:
        return False
    return not _is_test_file(path)


def _tested_stem(path: Path) -> str | None:
    """The source stem a test file targets (``test_foo.py``/``foo_test.py`` -> ``foo``)."""
    stem = path.stem
    if stem.startswith("test_"):
        return stem[len("test_") :]
    if stem.endswith("_test"):
        return stem[: -len("_test")]
    return None


def _index_test_files(
    tracked: list[Path],
) -> tuple[dict[str, list[Path]], dict[tuple[Path, str], list[Path]]]:
    """Index the tracked test files for the two pairing rules.

    Returns two indexes: tests under a ``tests/`` directory (at any
    depth) keyed by the stem they target, and every test file keyed by
    ``(directory, stem)`` for same-directory pairing.
    """
    by_stem: defaultdict[str, list[Path]] = defaultdict(list)
    by_dir_and_stem: defaultdict[tuple[Path, str], list[Path]] = defaultdict(list)
    for path in tracked:
        if path.suffix != ".py":
            continue
        stem = _tested_stem(path)
        if stem is None:
            continue
        if TESTS_DIR_NAME in path.parent.parts:
            by_stem[stem].append(path)
        by_dir_and_stem[(path.parent, stem)].append(path)
    return by_stem, by_dir_and_stem


def find_coverage_gaps(path: str | Path, exclude: tuple[str, ...] = ()) -> CoverageGapReport:
    """Pair the tracked Python source files with their test files.

    A source file ``foo.py`` counts as tested when the repository tracks
    ``test_foo.py`` or ``foo_test.py`` either anywhere under a
    ``tests/`` directory or in the same directory as the source. Test
    files themselves, ``__init__.py``, ``__main__.py``, ``setup.py``
    and non-Python files are excluded from the analysis.

    Args:
        path: Root directory of a Git working tree.
        exclude: Gitignore-style patterns; matching files are invisible
            to the pairing, both as sources and as tests.

    Returns:
        A :class:`CoverageGapReport` listing every source file with its
        pairing status, untested files first.

    Raises:
        NotAGitRepositoryError: If ``path`` is not a usable Git repository.
    """
    repo = open_repository(path)
    try:
        root = Path(repo.working_tree_dir).resolve()
        tracked = list_tracked_files(repo, exclude)
    finally:
        repo.close()

    sources = [file for file in tracked if _is_source_file(file)]
    tests_by_stem, tests_by_dir_and_stem = _index_test_files(tracked)
    stem_counts = Counter(source.stem for source in sources)

    statuses = []
    for source in sources:
        stem_matches = tests_by_stem.get(source.stem, [])
        same_dir_matches = tests_by_dir_and_stem.get((source.parent, source.stem), [])
        matched = tuple(sorted(dict.fromkeys(stem_matches + same_dir_matches), key=Path.as_posix))
        statuses.append(
            SourceFileStatus(
                path=source,
                has_test=bool(matched),
                matched_tests=matched,
                ambiguous=bool(stem_matches) and stem_counts[source.stem] > 1,
            )
        )
    statuses.sort(key=lambda status: (status.has_test, status.path.as_posix()))

    tested_count = sum(1 for status in statuses if status.has_test)
    source_file_count = len(statuses)
    return CoverageGapReport(
        repo_path=root,
        files=tuple(statuses),
        source_file_count=source_file_count,
        tested_count=tested_count,
        untested_count=source_file_count - tested_count,
        coverage_ratio=tested_count / source_file_count if source_file_count else 1.0,
    )
