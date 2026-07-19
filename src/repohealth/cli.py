"""Command-line interface for repohealth.

This module only orchestrates and renders: all analysis logic lives in
the modules under :mod:`repohealth.core`.
"""

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
    shown = files if show_all else files[:top]

    _render_complexity_report(report, shown)

    if threshold is not None and files:
        error_console.print(
            f"[bold red]{len(files)}[/bold red] [red]file(s) ranked at or worse than "
            f"'{threshold}' (threshold exceeded)[/red]"
        )
        raise typer.Exit(code=2)


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
