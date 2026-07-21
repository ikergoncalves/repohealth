"""Git history mining for hotspots, ownership and bus factor.

This module holds the pure, testable core of the ``repohealth hotspots``
and ``repohealth busfactor`` commands: it traverses the Git history once
with pydriller and, in that same pass, accumulates file churn, per-file
ownership and the author totals that determine the repository bus factor.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from pathlib import Path

from pydriller import Repository
from pydriller.domain.commit import Commit

from repohealth.core.config import build_exclude_matcher
from repohealth.core.repo_scanner import list_tracked_files, open_repository


@dataclass(frozen=True)
class FileChurn:
    """Change frequency of a single file across the analyzed history."""

    path: Path
    change_count: int
    author_count: int
    last_modified: datetime


@dataclass(frozen=True)
class FileOwnership:
    """Author contribution breakdown for a single file."""

    path: Path
    total_changes: int
    top_author: str
    top_author_share: float
    authors: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class HistoryReport:
    """Complete result of mining a repository's history.

    ``author_totals`` lists every author's total file changes sorted by
    contribution (descending); its first ``bus_factor`` entries are the
    authors in ``bus_factor_authors``.
    """

    repo_path: Path
    analyzed_commit_count: int
    hotspots: tuple[FileChurn, ...]
    ownership: tuple[FileOwnership, ...]
    bus_factor: int
    bus_factor_authors: tuple[str, ...]
    total_changes: int
    author_totals: tuple[tuple[str, int], ...]


def analyze_history(
    path: str | Path,
    since: datetime | None = None,
    max_commits: int | None = None,
    exclude: tuple[str, ...] = (),
) -> HistoryReport:
    """Mine the Git history for file churn, ownership and bus factor.

    The history is traversed exactly once. Merge commits are skipped so
    merged changes are not counted twice, renames migrate the churn
    accumulated under the old path to the new one, and files that no
    longer exist in HEAD are excluded from hotspots and ownership.
    Authors are identified by normalized e-mail (lowercased, stripped)
    but reported by their most recent name.

    Excluded files are invisible end to end: they never appear in
    hotspots or ownership, and their changes do not count as file
    changes for the bus factor or the author totals.

    Args:
        path: Root directory of a Git working tree.
        since: Only analyze commits from this date onwards.
        max_commits: Only analyze the N most recent commits.
        exclude: Gitignore-style patterns; matching files are ignored.

    Returns:
        A :class:`HistoryReport`. For a repository without commits (or
        when the filters match none) the report is empty, with
        ``analyzed_commit_count`` 0 and ``bus_factor`` 0.

    Raises:
        NotAGitRepositoryError: If ``path`` is not a usable Git repository.
    """
    repo = open_repository(path)
    try:
        root = Path(repo.working_tree_dir).resolve()
        has_commits = repo.head.is_valid()
        live_files = {rel_path.as_posix() for rel_path in list_tracked_files(repo, exclude)}
    finally:
        repo.close()

    excluded = build_exclude_matcher(exclude) if exclude else None

    change_counts: Counter[str] = Counter()
    file_authors: defaultdict[str, Counter[str]] = defaultdict(Counter)
    last_modified: dict[str, datetime] = {}
    author_changes: Counter[str] = Counter()
    name_by_email: dict[str, str] = {}
    analyzed_commit_count = 0

    if has_commits:
        for commit in _iter_commits(root, since, max_commits):
            analyzed_commit_count += 1
            email = (commit.author.email or "").strip().lower()
            name_by_email[email] = commit.author.name or email
            for modified in commit.modified_files:
                old = Path(modified.old_path).as_posix() if modified.old_path else None
                new = Path(modified.new_path).as_posix() if modified.new_path else None
                if old is not None and new is not None and old != new:
                    _migrate_rename(old, new, change_counts, file_authors, last_modified)
                current = new if new is not None else old
                if current is None:
                    continue
                if excluded is not None and excluded(Path(current)):
                    continue
                change_counts[current] += 1
                file_authors[current][email] += 1
                last_modified[current] = commit.committer_date
                author_changes[email] += 1

    hotspots = tuple(
        sorted(
            (
                FileChurn(
                    path=Path(path_str),
                    change_count=change_counts[path_str],
                    author_count=len(file_authors[path_str]),
                    last_modified=last_modified[path_str],
                )
                for path_str in change_counts
                if path_str in live_files
            ),
            key=lambda churn: (-churn.change_count, churn.path.as_posix()),
        )
    )
    ownership = tuple(
        _file_ownership(path_str, file_authors[path_str], name_by_email)
        for path_str in sorted(change_counts)
        if path_str in live_files
    )
    total_changes = sum(author_changes.values())
    author_totals = tuple(
        (name_by_email[email], count)
        for email, count in sorted(
            author_changes.items(), key=lambda item: (-item[1], name_by_email[item[0]])
        )
    )
    bus_factor_authors = _bus_factor_authors(author_totals, total_changes)
    return HistoryReport(
        repo_path=root,
        analyzed_commit_count=analyzed_commit_count,
        hotspots=hotspots,
        ownership=ownership,
        bus_factor=len(bus_factor_authors),
        bus_factor_authors=bus_factor_authors,
        total_changes=total_changes,
        author_totals=author_totals,
    )


def _iter_commits(root: Path, since: datetime | None, max_commits: int | None) -> Iterator[Commit]:
    """Yield the selected non-merge commits in chronological order.

    With ``max_commits`` the history is traversed newest-first so only
    the most recent commits are kept, then replayed chronologically so
    rename migration stays correct.
    """
    kwargs: dict[str, datetime] = {}
    if since is not None:
        kwargs["since"] = since
    if max_commits is None:
        commits = Repository(str(root), **kwargs).traverse_commits()
        yield from (commit for commit in commits if not commit.merge)
        return
    newest_first = Repository(str(root), order="reverse", **kwargs).traverse_commits()
    recent = islice((commit for commit in newest_first if not commit.merge), max_commits)
    yield from reversed(list(recent))


def _migrate_rename(
    old: str,
    new: str,
    change_counts: Counter[str],
    file_authors: defaultdict[str, Counter[str]],
    last_modified: dict[str, datetime],
) -> None:
    """Move the churn accumulated under ``old`` to the file's new path."""
    if old not in change_counts:
        return
    change_counts[new] += change_counts.pop(old)
    file_authors[new].update(file_authors.pop(old))
    moved = last_modified.pop(old)
    if new not in last_modified or last_modified[new] < moved:
        last_modified[new] = moved


def _file_ownership(
    path_str: str, counts: Counter[str], name_by_email: dict[str, str]
) -> FileOwnership:
    """Build the ownership record for one file from its per-author counts."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], name_by_email[item[0]]))
    total = sum(counts.values())
    authors = tuple((name_by_email[email], count) for email, count in ordered)
    return FileOwnership(
        path=Path(path_str),
        total_changes=total,
        top_author=authors[0][0],
        top_author_share=authors[0][1] / total,
        authors=authors,
    )


def _bus_factor_authors(
    author_totals: tuple[tuple[str, int], ...], total_changes: int
) -> tuple[str, ...]:
    """Fewest top authors whose combined changes reach at least half the total."""
    if total_changes == 0:
        return ()
    selected: list[str] = []
    cumulative = 0
    for name, count in author_totals:
        selected.append(name)
        cumulative += count
        if 2 * cumulative >= total_changes:
            break
    return tuple(selected)
