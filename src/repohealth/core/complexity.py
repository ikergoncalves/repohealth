"""Cyclomatic complexity analysis for Git-tracked Python files.

This module holds the pure, testable core of the ``repohealth complexity``
command: it runs radon's cyclomatic complexity visitor over every tracked
``.py`` file and aggregates the results into a report.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from radon.complexity import cc_rank, cc_visit
from radon.visitors import Class, Function

from repohealth.core.repo_scanner import list_tracked_files, open_repository


@dataclass(frozen=True)
class FunctionComplexity:
    """Cyclomatic complexity of a single function or method."""

    name: str
    lineno: int
    complexity: int
    rank: str


@dataclass(frozen=True)
class FileComplexity:
    """Aggregated cyclomatic complexity of one Python file.

    Files without any functions or methods (e.g. an empty ``__init__.py``)
    have an empty ``functions`` tuple, an average of ``0.0`` and rank ``A``.
    """

    path: Path
    functions: tuple[FunctionComplexity, ...]
    average_complexity: float
    max_complexity: int
    rank: str


@dataclass(frozen=True)
class ComplexityReport:
    """Complete result of analyzing a repository's Python files."""

    repo_path: Path
    files: tuple[FileComplexity, ...]
    analyzed_file_count: int
    skipped_files: tuple[Path, ...]


def rank_for(complexity: float) -> str:
    """Return radon's A-F rank for a complexity value, mapping ``0`` to ``A``."""
    return cc_rank(complexity) if complexity > 0 else "A"


def analyze_complexity(path: str | Path, exclude: tuple[str, ...] = ()) -> ComplexityReport:
    """Analyze the cyclomatic complexity of all tracked Python files.

    Args:
        path: Root directory of a Git working tree.
        exclude: Gitignore-style patterns; matching files are ignored.

    Returns:
        A :class:`ComplexityReport` with per-file results sorted by
        ``max_complexity`` and then ``average_complexity``, both descending.
        Python files that cannot be decoded as UTF-8 or fail to parse are
        collected in ``skipped_files`` instead of aborting the analysis.

    Raises:
        NotAGitRepositoryError: If ``path`` is not a usable Git repository.
    """
    repo = open_repository(path)
    try:
        root = Path(repo.working_tree_dir).resolve()
        python_files = [
            rel_path
            for rel_path in list_tracked_files(repo, exclude)
            if rel_path.suffix.lower() == ".py"
        ]
    finally:
        repo.close()

    analyzed: list[FileComplexity] = []
    skipped: list[Path] = []
    for rel_path in python_files:
        file_complexity = _analyze_file(root, rel_path)
        if file_complexity is None:
            skipped.append(rel_path)
        else:
            analyzed.append(file_complexity)

    analyzed.sort(
        key=lambda file: (-file.max_complexity, -file.average_complexity, file.path.as_posix())
    )
    return ComplexityReport(
        repo_path=root,
        files=tuple(analyzed),
        analyzed_file_count=len(analyzed),
        skipped_files=tuple(skipped),
    )


def repository_average_complexity(report: ComplexityReport) -> float:
    """Mean cyclomatic complexity across all functions in the report."""
    complexities = [function.complexity for file in report.files for function in file.functions]
    if not complexities:
        return 0.0
    return sum(complexities) / len(complexities)


def _analyze_file(root: Path, rel_path: Path) -> FileComplexity | None:
    """Analyze one Python file, returning ``None`` when it cannot be parsed."""
    try:
        source = (root / rel_path).read_bytes().decode("utf-8")
        blocks = cc_visit(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None

    functions = tuple(
        FunctionComplexity(
            name=block.name,
            lineno=block.lineno,
            complexity=block.complexity,
            rank=cc_rank(block.complexity),
        )
        for block in sorted(_iter_functions(blocks), key=lambda block: block.lineno)
    )
    average = (
        sum(function.complexity for function in functions) / len(functions) if functions else 0.0
    )
    return FileComplexity(
        path=rel_path,
        functions=functions,
        average_complexity=average,
        max_complexity=max((function.complexity for function in functions), default=0),
        rank=rank_for(average),
    )


def _iter_functions(blocks: Iterable[Function | Class]) -> Iterator[Function]:
    """Flatten radon blocks into plain functions, descending into classes and closures."""
    for block in blocks:
        if isinstance(block, Function):
            yield block
            yield from _iter_functions(block.closures)
        elif isinstance(block, Class):
            yield from _iter_functions(block.methods)
            yield from _iter_functions(getattr(block, "inner_classes", ()))
