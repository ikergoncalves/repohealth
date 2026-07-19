"""Scanning logic for Git repositories.

This module holds the pure, testable core of the ``repohealth scan``
command: it lists the files tracked by Git, classifies them by language,
counts their lines and aggregates everything into a report.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".swift": "Swift",
    ".kt": "Kotlin",
}
OTHER_LANGUAGE = "Other"


class NotAGitRepositoryError(Exception):
    """Raised when a path does not point to a usable Git repository."""


@dataclass(frozen=True)
class FileStats:
    """Statistics for a single Git-tracked file.

    ``lines`` is ``None`` when the file could not be read as UTF-8 text
    (e.g. binary files), in which case it contributes zero lines.
    """

    path: Path
    language: str
    lines: int | None


@dataclass(frozen=True)
class LanguageStats:
    """Aggregated statistics for all files of one language."""

    language: str
    file_count: int
    line_count: int
    percent_of_lines: float


@dataclass(frozen=True)
class RepoReport:
    """Complete result of scanning a repository."""

    repo_name: str
    repo_path: Path
    files: tuple[FileStats, ...]
    languages: tuple[LanguageStats, ...]
    total_files: int
    total_lines: int


def open_repository(path: str | Path) -> Repo:
    """Open ``path`` as a Git repository.

    Args:
        path: Directory expected to be the root of a Git working tree.

    Returns:
        The opened GitPython repository. Callers are responsible for
        closing it.

    Raises:
        NotAGitRepositoryError: If the path does not exist, is not a Git
            repository, or is a bare repository without a working tree.
    """
    try:
        repo = Repo(path)
    except NoSuchPathError as exc:
        raise NotAGitRepositoryError(f"Path does not exist: '{path}'") from exc
    except InvalidGitRepositoryError as exc:
        raise NotAGitRepositoryError(f"Not a Git repository (no .git found): '{path}'") from exc
    if repo.bare or repo.working_tree_dir is None:
        repo.close()
        raise NotAGitRepositoryError(f"Bare repository, nothing to scan: '{path}'")
    return repo


def list_tracked_files(repo: Repo) -> list[Path]:
    """List all files tracked in the Git index, relative to the repository root."""
    return sorted(Path(entry_path) for entry_path, stage in repo.index.entries if stage == 0)


def classify_language(path: Path) -> str:
    """Map a file to a language name by its extension, defaulting to ``Other``."""
    return LANGUAGE_BY_EXTENSION.get(path.suffix.lower(), OTHER_LANGUAGE)


def count_lines(file_path: Path) -> int | None:
    """Count the lines of a UTF-8 text file.

    Returns ``None`` for files that cannot be read or decoded as UTF-8
    (e.g. binaries), so callers can skip them safely.
    """
    try:
        text = file_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return len(text.splitlines())


def scan_repository(path: str | Path) -> RepoReport:
    """Scan a Git repository and aggregate its tracked files by language.

    Args:
        path: Root directory of a Git working tree.

    Returns:
        A :class:`RepoReport` with per-file and per-language statistics,
        languages sorted by total lines in descending order.

    Raises:
        NotAGitRepositoryError: If ``path`` is not a usable Git repository.
    """
    repo = open_repository(path)
    try:
        root = Path(repo.working_tree_dir).resolve()
        files = tuple(
            FileStats(
                path=rel_path,
                language=classify_language(rel_path),
                lines=count_lines(root / rel_path),
            )
            for rel_path in list_tracked_files(repo)
        )
    finally:
        repo.close()

    languages = _aggregate_languages(files)
    return RepoReport(
        repo_name=root.name,
        repo_path=root,
        files=files,
        languages=languages,
        total_files=len(files),
        total_lines=sum(stats.line_count for stats in languages),
    )


def _aggregate_languages(files: tuple[FileStats, ...]) -> tuple[LanguageStats, ...]:
    """Group per-file stats into per-language totals, sorted by lines desc."""
    file_counts: defaultdict[str, int] = defaultdict(int)
    line_counts: defaultdict[str, int] = defaultdict(int)
    for stats in files:
        file_counts[stats.language] += 1
        line_counts[stats.language] += stats.lines or 0

    total_lines = sum(line_counts.values())
    aggregated = [
        LanguageStats(
            language=language,
            file_count=file_counts[language],
            line_count=line_counts[language],
            percent_of_lines=100.0 * line_counts[language] / total_lines if total_lines else 0.0,
        )
        for language in file_counts
    ]
    aggregated.sort(key=lambda stats: (-stats.line_count, stats.language))
    return tuple(aggregated)
