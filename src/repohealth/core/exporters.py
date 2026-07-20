"""Exporters that render a :class:`HealthReport` as JSON, Markdown or HTML.

All exporters are pure functions from a report to a string, using only
the standard library: :mod:`json` for the JSON document, plain text for
Markdown and :func:`html.escape` for the self-contained HTML page.
"""

import json
from html import escape

from repohealth import __version__
from repohealth.core.health import HealthReport

_TOP_FILES = 5


def to_json(report: HealthReport) -> str:
    """Serialize the full report as a stable, indented JSON document."""
    payload = {
        "version": __version__,
        "generated_at": report.generated_at.isoformat(),
        "repo_name": report.repo_path.name,
        "repo_path": report.repo_path.as_posix(),
        "score": round(report.score, 2),
        "grade": report.grade,
        "components": [
            {
                "name": component.name,
                "score": round(component.score, 2),
                "weight": component.weight,
                "detail": component.detail,
            }
            for component in report.components
        ],
        "risk_files": [
            {
                "path": risk.path.as_posix(),
                "change_count": risk.change_count,
                "max_complexity": risk.max_complexity,
                "rank": risk.rank,
            }
            for risk in report.risk_files
        ],
        "scan": {
            "total_files": report.scan.total_files,
            "total_lines": report.scan.total_lines,
            "languages": [
                {
                    "language": stats.language,
                    "file_count": stats.file_count,
                    "line_count": stats.line_count,
                    "percent_of_lines": round(stats.percent_of_lines, 2),
                }
                for stats in report.scan.languages
            ],
        },
        "complexity": {
            "analyzed_file_count": report.complexity.analyzed_file_count,
            "skipped_files": [path.as_posix() for path in report.complexity.skipped_files],
            "files": [
                {
                    "path": file.path.as_posix(),
                    "function_count": len(file.functions),
                    "average_complexity": round(file.average_complexity, 2),
                    "max_complexity": file.max_complexity,
                    "rank": file.rank,
                }
                for file in report.complexity.files
            ],
        },
        "history": {
            "analyzed_commit_count": report.history.analyzed_commit_count,
            "total_changes": report.history.total_changes,
            "bus_factor": report.history.bus_factor,
            "bus_factor_authors": list(report.history.bus_factor_authors),
            "author_totals": [
                {"author": name, "changes": count} for name, count in report.history.author_totals
            ],
            "hotspots": [
                {
                    "path": churn.path.as_posix(),
                    "change_count": churn.change_count,
                    "author_count": churn.author_count,
                    "last_modified": churn.last_modified.isoformat(),
                }
                for churn in report.history.hotspots
            ],
        },
        "coverage": {
            "source_file_count": report.coverage.source_file_count,
            "tested_count": report.coverage.tested_count,
            "untested_count": report.coverage.untested_count,
            "coverage_ratio": round(report.coverage.coverage_ratio, 4),
            "files": [
                {
                    "path": status.path.as_posix(),
                    "has_test": status.has_test,
                    "ambiguous": status.ambiguous,
                    "matched_tests": [test.as_posix() for test in status.matched_tests],
                }
                for status in report.coverage.files
            ],
        },
    }
    return json.dumps(payload, indent=2)


def to_markdown(report: HealthReport) -> str:
    """Render the report as a human-readable Markdown document."""
    lines = [
        f"# repohealth report — {report.repo_path.name}",
        "",
        f"**Score: {report.score:.1f} / 100 — Grade {report.grade}**",
        "",
        f"Generated at {report.generated_at.isoformat()} by repohealth {__version__}.",
        "",
        "## Components",
        "",
        "| Component | Score | Weight | Detail |",
        "| --- | ---: | ---: | --- |",
    ]
    lines.extend(
        f"| {component.name} | {component.score:.1f} | {component.weight:.0%} "
        f"| {component.detail} |"
        for component in report.components
    )

    if report.risk_files:
        lines += [
            "",
            "## Risk files (hot and complex)",
            "",
            "| File | Changes | Max CC | Rank |",
            "| --- | ---: | ---: | :-: |",
        ]
        lines.extend(
            f"| `{risk.path.as_posix()}` | {risk.change_count} "
            f"| {risk.max_complexity} | {risk.rank} |"
            for risk in report.risk_files
        )

    lines += ["", f"## Hotspots (top {_TOP_FILES})", ""]
    if report.history.hotspots:
        lines += ["| File | Changes | Authors | Last modified |", "| --- | ---: | ---: | --- |"]
        lines.extend(
            f"| `{churn.path.as_posix()}` | {churn.change_count} | {churn.author_count} "
            f"| {churn.last_modified.strftime('%Y-%m-%d')} |"
            for churn in report.history.hotspots[:_TOP_FILES]
        )
    else:
        lines.append("No history to analyze.")

    lines += ["", f"## Most complex files (top {_TOP_FILES})", ""]
    if report.complexity.files:
        lines += ["| File | Avg CC | Max CC | Rank |", "| --- | ---: | ---: | :-: |"]
        lines.extend(
            f"| `{file.path.as_posix()}` | {file.average_complexity:.1f} "
            f"| {file.max_complexity} | {file.rank} |"
            for file in report.complexity.files[:_TOP_FILES]
        )
    else:
        lines.append("No Python files analyzed.")

    lines += ["", "## Untested source files", ""]
    untested = [status for status in report.coverage.files if not status.has_test]
    if untested:
        lines.extend(f"- `{status.path.as_posix()}`" for status in untested)
    else:
        lines.append("Every source file has a matching test.")
    lines += [
        "",
        f"{report.coverage.tested_count} of {report.coverage.source_file_count} "
        f"source files have a matching test "
        f"({100 * report.coverage.coverage_ratio:.1f}%).",
    ]

    lines += ["", "## Bus factor", ""]
    if report.history.analyzed_commit_count:
        authors = ", ".join(report.history.bus_factor_authors)
        lines.append(
            f"Bus factor **{report.history.bus_factor}**: {authors} account(s) for at "
            f"least half of the {report.history.total_changes} file change(s) across "
            f"{report.history.analyzed_commit_count} commit(s)."
        )
    else:
        lines.append("No history to analyze.")

    return "\n".join(lines) + "\n"


_GRADE_COLORS = {
    "A": "#2e7d32",
    "B": "#2e7d32",
    "C": "#f9a825",
    "D": "#ef6c00",
    "E": "#c62828",
    "F": "#c62828",
}

_CSS = """
:root { color-scheme: light; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; background: #f5f6f8; color: #1f2430; }
main { max-width: 60rem; margin: 0 auto; padding: 2rem 1.5rem 4rem; }
header { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap;
         padding: 1.5rem 0; border-bottom: 2px solid #e0e3e8; }
h1 { font-size: 1.6rem; margin: 0; }
h2 { font-size: 1.15rem; margin: 2.2rem 0 0.8rem; }
.path { color: #6b7280; font-size: 0.85rem; margin-top: 0.2rem; }
.score { font-size: 3rem; font-weight: 700; }
.score small { font-size: 1.2rem; color: #6b7280; font-weight: 400; }
.badge { display: inline-block; min-width: 2.6rem; text-align: center; padding: 0.5rem 0.9rem;
         border-radius: 0.5rem; color: #fff; font-size: 1.8rem; font-weight: 700; }
table { border-collapse: collapse; width: 100%; background: #fff;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08); }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #e8eaef;
         font-size: 0.9rem; }
th { background: #eef0f4; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
code { font-family: ui-monospace, Consolas, monospace; font-size: 0.85rem; }
.note { color: #6b7280; font-size: 0.85rem; }
footer { margin-top: 3rem; color: #9ca3af; font-size: 0.8rem; }
"""


def _html_table(headers: tuple[str, ...], rows: list[tuple[str, ...]], numeric: set[int]) -> str:
    """Build an HTML table; every cell is escaped, ``numeric`` columns right-aligned."""
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="num">{escape(cell)}</td>'
            if index in numeric
            else f"<td>{escape(cell)}</td>"
            for index, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def to_html(report: HealthReport) -> str:
    """Render the report as a self-contained HTML page (no external assets)."""
    grade_color = _GRADE_COLORS[report.grade]
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>repohealth — {escape(report.repo_path.name)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<header>",
        f"<div><h1>repohealth report — {escape(report.repo_path.name)}</h1>"
        f'<div class="path">{escape(report.repo_path.as_posix())}</div></div>',
        f'<div class="score">{report.score:.1f}<small> / 100</small></div>',
        f'<span class="badge" style="background:{grade_color}">{escape(report.grade)}</span>',
        "</header>",
    ]

    parts.append("<h2>Components</h2>")
    parts.append(
        _html_table(
            ("Component", "Score", "Weight", "Detail"),
            [
                (
                    component.name,
                    f"{component.score:.1f}",
                    f"{component.weight:.0%}",
                    component.detail,
                )
                for component in report.components
            ],
            numeric={1, 2},
        )
    )

    parts.append("<h2>Risk files (hot and complex)</h2>")
    if report.risk_files:
        parts.append(
            _html_table(
                ("File", "Changes", "Max CC", "Rank"),
                [
                    (
                        risk.path.as_posix(),
                        str(risk.change_count),
                        str(risk.max_complexity),
                        risk.rank,
                    )
                    for risk in report.risk_files
                ],
                numeric={1, 2},
            )
        )
    else:
        parts.append('<p class="note">No file is both hot and complex.</p>')

    parts.append(f"<h2>Hotspots (top {_TOP_FILES})</h2>")
    if report.history.hotspots:
        parts.append(
            _html_table(
                ("File", "Changes", "Authors", "Last modified"),
                [
                    (
                        churn.path.as_posix(),
                        str(churn.change_count),
                        str(churn.author_count),
                        churn.last_modified.strftime("%Y-%m-%d"),
                    )
                    for churn in report.history.hotspots[:_TOP_FILES]
                ],
                numeric={1, 2},
            )
        )
    else:
        parts.append('<p class="note">No history to analyze.</p>')

    parts.append(f"<h2>Most complex files (top {_TOP_FILES})</h2>")
    if report.complexity.files:
        parts.append(
            _html_table(
                ("File", "Avg CC", "Max CC", "Rank"),
                [
                    (
                        file.path.as_posix(),
                        f"{file.average_complexity:.1f}",
                        str(file.max_complexity),
                        file.rank,
                    )
                    for file in report.complexity.files[:_TOP_FILES]
                ],
                numeric={1, 2},
            )
        )
    else:
        parts.append('<p class="note">No Python files analyzed.</p>')

    parts.append("<h2>Untested source files</h2>")
    untested = [status for status in report.coverage.files if not status.has_test]
    if untested:
        items = "".join(
            f"<li><code>{escape(status.path.as_posix())}</code></li>" for status in untested
        )
        parts.append(f"<ul>{items}</ul>")
    else:
        parts.append('<p class="note">Every source file has a matching test.</p>')
    parts.append(
        f"<p>{report.coverage.tested_count} of {report.coverage.source_file_count} "
        f"source files have a matching test "
        f"({100 * report.coverage.coverage_ratio:.1f}%).</p>"
    )

    parts.append("<h2>Bus factor</h2>")
    if report.history.analyzed_commit_count:
        authors = ", ".join(report.history.bus_factor_authors)
        parts.append(
            f"<p>Bus factor <strong>{report.history.bus_factor}</strong>: "
            f"{escape(authors)} account(s) for at least half of the "
            f"{report.history.total_changes} file change(s) across "
            f"{report.history.analyzed_commit_count} commit(s).</p>"
        )
        parts.append(
            _html_table(
                ("Author", "Changes"),
                [(name, str(count)) for name, count in report.history.author_totals],
                numeric={1},
            )
        )
    else:
        parts.append('<p class="note">No history to analyze.</p>')

    parts.append(
        f"<footer>Generated at {escape(report.generated_at.isoformat())} "
        f"by repohealth {escape(__version__)}</footer>"
    )
    parts += ["</main>", "</body>", "</html>"]
    return "\n".join(parts) + "\n"
