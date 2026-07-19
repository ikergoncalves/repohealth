"""Command-line interface for repohealth.

This module only orchestrates and renders: all scanning logic lives in
:mod:`repohealth.core.repo_scanner`.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from repohealth import __version__
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
