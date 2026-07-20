"""Command-line interface for repohealth.

This module only orchestrates and renders: all analysis logic lives in
the modules under :mod:`repohealth.core`.
"""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from repohealth import __version__
from repohealth.core.complexity import (
    ComplexityReport,
    FileComplexity,
    analyze_complexity,
    rank_for,
    repository_average_complexity,
)
from repohealth.core.coverage_gaps import (
    CoverageGapReport,
    SourceFileStatus,
    find_coverage_gaps,
)
from repohealth.core.history import FileChurn, HistoryReport, analyze_history
from repohealth.core.repo_scanner import NotAGitRepositoryError, RepoReport, scan_repository

app = typer.Typer(
    name="repohealth",
    help="Analyze the health of a local Git repository.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"repohealth {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the application version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Analyze the health of a local Git repository."""


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a local Git repository."),
    ] = Path("."),
) -> None:
    """Scan a Git repository and show tracked files grouped by language."""
    try:
        report = scan_repository(path)
    except NotAGitRepositoryError as exc:
        error_console.print(f"[bold red]Error:[/bold red] [red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    _render_report(report)


RANKS = "ABCDEF"
_RANK_STYLES = {
    "A": "green",
    "B": "green",
    "C": "yellow",
    "D": "dark_orange",
    "E": "bold red",
    "F": "bold red",
}


def _styled_rank(rank: str) -> str:
    style = _RANK_STYLES.get(rank, "white")
    return f"[{style}]{rank}[/{style}]"


def _threshold_callback(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper()
    if normalized not in RANKS:
        raise typer.BadParameter("Threshold must be a single rank letter from A to F.")
    return normalized


@app.command()
def complexity(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a local Git repository."),
    ] = Path("."),
    top: Annotated[
        int,
        typer.Option("--top", help="Show only the N most complex files."),
    ] = 10,
    threshold: Annotated[
        str | None,
        typer.Option(
            "--threshold",
            help=(
                "Only list files ranked at or worse than this rank (A-F); "
                "exit with code 2 if any file matches."
            ),
            callback=_threshold_callback,
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all files, ignoring --top."),
    ] = False,
) -> None:
    """Analyze the cyclomatic complexity of the tracked Python files."""
    try:
        report = analyze_complexity(path)
    except NotAGitRepositoryError as exc:
        error_console.print(f"[bold red]Error:[/bold red] [red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc

    files = report.files
    if threshold is not None:
        files = tuple(file for file in files if file.rank >= threshold)
        if not files:
            _print_repo_header(report.repo_path)
            console.print(f"[green]No files at or worse than rank {threshold}[/green]")
            return
    shown = files if show_all else files[:top]

    _render_complexity_report(report, shown)

    if threshold is not None and files:
        error_console.print(
            f"[bold red]{len(files)}[/bold red] [red]file(s) ranked at or worse than "
            f"'{threshold}' (threshold exceeded)[/red]"
        )
        raise typer.Exit(code=2)


def _parse_since(value: str | None) -> datetime | None:
    """Parse a ``--since`` value as YYYY-MM-DD, exiting with an error if invalid."""
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        error_console.print(
            f"[bold red]Error:[/bold red] [red]Invalid --since date '{escape(value)}': "
            "expected format YYYY-MM-DD[/red]"
        )
        raise typer.Exit(code=1) from None


def _analyze_history_or_exit(
    path: Path, since: str | None, max_commits: int | None
) -> HistoryReport:
    """Run the history analysis, translating known failures into exit codes."""
    try:
        return analyze_history(path, since=_parse_since(since), max_commits=max_commits)
    except NotAGitRepositoryError as exc:
        error_console.print(f"[bold red]Error:[/bold red] [red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


def _exit_if_no_history(report: HistoryReport) -> None:
    """Exit successfully with a notice when there are no commits to analyze."""
    if report.analyzed_commit_count == 0:
        console.print("[yellow]no history to analyze[/yellow]")
        raise typer.Exit()


_SINCE_OPTION = typer.Option(
    "--since", help="Only analyze commits from this date onwards (YYYY-MM-DD)."
)
_MAX_COMMITS_OPTION = typer.Option("--max-commits", help="Only analyze the N most recent commits.")


@app.command()
def hotspots(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a local Git repository."),
    ] = Path("."),
    top: Annotated[
        int,
        typer.Option("--top", help="Show only the N most changed files."),
    ] = 10,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all files, ignoring --top."),
    ] = False,
    since: Annotated[str | None, _SINCE_OPTION] = None,
    max_commits: Annotated[int | None, _MAX_COMMITS_OPTION] = None,
) -> None:
    """Show the files most frequently changed across the Git history."""
    report = _analyze_history_or_exit(path, since, max_commits)
    _exit_if_no_history(report)
    shown = report.hotspots if show_all else report.hotspots[:top]
    _render_hotspots_report(report, shown)


@app.command()
def busfactor(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a local Git repository."),
    ] = Path("."),
    since: Annotated[str | None, _SINCE_OPTION] = None,
    max_commits: Annotated[int | None, _MAX_COMMITS_OPTION] = None,
) -> None:
    """Show the bus factor: the fewest authors covering half of all changes."""
    report = _analyze_history_or_exit(path, since, max_commits)
    _exit_if_no_history(report)
    _render_busfactor_report(report)


@app.command()
def untested(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a local Git repository."),
    ] = Path("."),
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Also show the source files that have a matching test."),
    ] = False,
) -> None:
    """Show tracked Python source files without a matching test file."""
    try:
        report = find_coverage_gaps(path)
    except NotAGitRepositoryError as exc:
        error_console.print(f"[bold red]Error:[/bold red] [red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc

    if report.source_file_count == 0:
        console.print("[yellow]no Python source files to analyze[/yellow]")
        raise typer.Exit()

    shown = report.files if show_all else tuple(f for f in report.files if not f.has_test)
    _render_untested_report(report, shown)


def _print_repo_header(repo_path: Path) -> None:
    """Print the standard repohealth panel identifying the repository."""
    header = f"[bold cyan]{escape(repo_path.name)}[/bold cyan]\n[dim]{escape(str(repo_path))}[/dim]"
    console.print(Panel.fit(header, title="repohealth", border_style="cyan"))


def _churn_style(change_count: int, max_change_count: int) -> str:
    """Style for a change count relative to the repository's hottest file."""
    if change_count >= 0.75 * max_change_count:
        return "bold red"
    if change_count >= 0.4 * max_change_count:
        return "yellow"
    return "green"


def _render_hotspots_report(report: HistoryReport, shown: tuple[FileChurn, ...]) -> None:
    """Render the hotspots report as a Rich panel, table and summary line."""
    _print_repo_header(report.repo_path)

    table = Table(title="Most frequently changed files")
    table.add_column("File", style="bold")
    table.add_column("Changes", justify="right")
    table.add_column("Authors", justify="right")
    table.add_column("Last modified", justify="right")
    max_change_count = report.hotspots[0].change_count if report.hotspots else 0
    for churn in shown:
        style = _churn_style(churn.change_count, max_change_count)
        table.add_row(
            churn.path.as_posix(),
            f"[{style}]{churn.change_count:,}[/{style}]",
            f"{churn.author_count:,}",
            churn.last_modified.strftime("%Y-%m-%d"),
        )
    console.print(table)

    summary = f"Analyzed [bold]{report.analyzed_commit_count:,}[/bold] commit(s)"
    if report.hotspots:
        hottest = report.hotspots[0]
        summary += (
            f", hottest file: [bold]{escape(hottest.path.as_posix())}[/bold] "
            f"({hottest.change_count:,} change(s))"
        )
    console.print(summary)


def _bus_factor_style(bus_factor: int) -> str:
    """Style for the bus factor panel: lower is riskier."""
    if bus_factor <= 1:
        return "red"
    if bus_factor == 2:
        return "yellow"
    return "green"


def _render_busfactor_report(report: HistoryReport) -> None:
    """Render the bus factor report as Rich panels, a table and a summary line."""
    _print_repo_header(report.repo_path)

    style = _bus_factor_style(report.bus_factor)
    console.print(
        Panel.fit(
            f"[bold {style}]Bus factor: {report.bus_factor}[/bold {style}]",
            border_style=style,
        )
    )
    if report.bus_factor == 1:
        console.print("[bold red]Warning: knowledge concentrated in a single author[/bold red]")

    table = Table(title="Authors covering 50% of all file changes")
    table.add_column("Author", style="bold")
    table.add_column("Changes", justify="right")
    table.add_column("% of total", justify="right")
    table.add_column("Cumulative %", justify="right")
    cumulative = 0
    for name, count in report.author_totals[: report.bus_factor]:
        cumulative += count
        table.add_row(
            escape(name),
            f"{count:,}",
            f"{100 * count / report.total_changes:.1f}%",
            f"{100 * cumulative / report.total_changes:.1f}%",
        )
    console.print(table)

    console.print(
        f"Analyzed [bold]{report.analyzed_commit_count:,}[/bold] commit(s) with "
        f"[bold]{report.total_changes:,}[/bold] file change(s) by "
        f"[bold]{len(report.author_totals):,}[/bold] author(s)"
    )


def _source_status_markup(status: SourceFileStatus) -> str:
    """Rich markup for a source file's pairing status."""
    if not status.has_test:
        return "[red]missing[/red]"
    if status.ambiguous:
        return "[yellow]tested*[/yellow]"
    return "[green]tested[/green]"


def _coverage_style(ratio: float) -> str:
    """Style for the coverage summary line: higher is healthier."""
    if ratio >= 0.8:
        return "green"
    if ratio >= 0.5:
        return "yellow"
    return "red"


def _render_untested_report(report: CoverageGapReport, shown: tuple[SourceFileStatus, ...]) -> None:
    """Render the coverage gap report as a Rich panel, table and summary line."""
    _print_repo_header(report.repo_path)

    if shown:
        table = Table(title="Source files and their matching tests")
        table.add_column("Source file", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Matched test(s)")
        for status in shown:
            matched = ", ".join(test.as_posix() for test in status.matched_tests)
            table.add_row(status.path.as_posix(), _source_status_markup(status), matched or "-")
        console.print(table)

    if any(status.ambiguous for status in shown):
        console.print(
            "[dim]* matched by file stem only: the test may belong to another "
            "source file with the same name[/dim]"
        )

    style = _coverage_style(report.coverage_ratio)
    console.print(
        f"[{style}]{report.tested_count} of {report.source_file_count} source files "
        f"have a matching test ({100 * report.coverage_ratio:.1f}%)[/{style}]"
    )


def _render_complexity_report(report: ComplexityReport, shown: tuple[FileComplexity, ...]) -> None:
    """Render the complexity report as a Rich panel, table and summary line."""
    header = (
        f"[bold cyan]{escape(report.repo_path.name)}[/bold cyan]\n"
        f"[dim]{escape(str(report.repo_path))}[/dim]"
    )
    console.print(Panel.fit(header, title="repohealth", border_style="cyan"))

    table = Table(title="Cyclomatic complexity of tracked Python files")
    table.add_column("File", style="bold")
    table.add_column("Functions", justify="right")
    table.add_column("Avg CC", justify="right")
    table.add_column("Max CC", justify="right")
    table.add_column("Rank", justify="center")
    for file in shown:
        table.add_row(
            file.path.as_posix(),
            f"{len(file.functions):,}",
            f"{file.average_complexity:.1f}",
            f"{file.max_complexity:,}",
            _styled_rank(file.rank),
        )
    console.print(table)

    if report.skipped_files:
        skipped = ", ".join(path.as_posix() for path in report.skipped_files)
        console.print(f"[yellow]Warning: skipped unparsable file(s): {escape(skipped)}[/yellow]")

    average = repository_average_complexity(report)
    console.print(
        f"Analyzed [bold]{report.analyzed_file_count:,}[/bold] Python file(s), "
        f"repository average CC [bold]{average:.1f}[/bold] "
        f"(rank {_styled_rank(rank_for(average))})"
    )


def _render_report(report: RepoReport) -> None:
    """Render the scan report as a Rich panel, table and summary line."""
    header = (
        f"[bold cyan]{escape(report.repo_name)}[/bold cyan]\n"
        f"[dim]{escape(str(report.repo_path))}[/dim]"
    )
    console.print(Panel.fit(header, title="repohealth", border_style="cyan"))

    table = Table(title="Tracked files by language")
    table.add_column("Language", style="bold")
    table.add_column("Files", justify="right")
    table.add_column("Lines", justify="right")
    table.add_column("% of lines", justify="right")
    for stats in report.languages:
        table.add_row(
            stats.language,
            f"{stats.file_count:,}",
            f"{stats.line_count:,}",
            f"{stats.percent_of_lines:.1f}%",
        )
    console.print(table)

    console.print(
        f"Total: [bold]{report.total_files:,}[/bold] tracked files, "
        f"[bold]{report.total_lines:,}[/bold] lines"
    )
