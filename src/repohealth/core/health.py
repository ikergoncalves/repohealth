"""Consolidated health scoring for a Git repository.

This module holds the pure, testable core of the ``repohealth report``
command: it runs the four existing analyses (scan, complexity, history
and coverage gaps) and combines them into a single weighted 0-100 score
with a per-component breakdown and the list of risk files — files that
are both frequently changed and complex.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from repohealth.core.complexity import ComplexityReport, analyze_complexity
from repohealth.core.coverage_gaps import CoverageGapReport, find_coverage_gaps
from repohealth.core.history import HistoryReport, analyze_history
from repohealth.core.repo_scanner import RepoReport, scan_repository

COMPLEXITY_WEIGHT = 0.30
COVERAGE_WEIGHT = 0.25
BUS_FACTOR_WEIGHT = 0.20
CHURN_RISK_WEIGHT = 0.25

HEALTHY_RANKS = frozenset({"A", "B"})


@dataclass(frozen=True)
class ComponentScore:
    """One weighted component of the overall health score."""

    name: str
    score: float
    weight: float
    detail: str


@dataclass(frozen=True)
class RiskFile:
    """A file that is simultaneously hot (high churn) and complex."""

    path: Path
    change_count: int
    max_complexity: int
    rank: str


@dataclass(frozen=True)
class HealthReport:
    """Complete consolidated health report of a repository.

    ``score`` is the weighted sum of the component scores and
    ``risk_files`` is sorted by ``change_count`` descending.
    """

    repo_path: Path
    generated_at: datetime
    score: float
    grade: str
    components: tuple[ComponentScore, ...]
    risk_files: tuple[RiskFile, ...]
    scan: RepoReport
    complexity: ComplexityReport
    history: HistoryReport
    coverage: CoverageGapReport


def grade_for(score: float) -> str:
    """Map a 0-100 health score to a letter grade from A to F."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    if score >= 35:
        return "E"
    return "F"


def bus_factor_score(bus_factor: int) -> float:
    """Score the bus factor: 0 (no history) is neutral, 1 is the riskiest."""
    if bus_factor == 1:
        return 30.0
    if bus_factor == 2:
        return 70.0
    return 100.0


def build_health_report(
    path: str | Path,
    since: datetime | None = None,
    max_commits: int | None = None,
) -> HealthReport:
    """Run the four analyses and combine them into a health report.

    Args:
        path: Root directory of a Git working tree.
        since: Only analyze commits from this date onwards.
        max_commits: Only analyze the N most recent commits.

    Returns:
        A :class:`HealthReport` with the weighted score, grade, component
        breakdown, risk files and the four underlying reports.

    Raises:
        NotAGitRepositoryError: If ``path`` is not a usable Git repository.
    """
    scan = scan_repository(path)
    complexity = analyze_complexity(path)
    history = analyze_history(path, since=since, max_commits=max_commits)
    coverage = find_coverage_gaps(path)

    churn_component, risk_files = _churn_risk(history, complexity)
    components = (
        _complexity_component(complexity),
        _coverage_component(coverage),
        _bus_factor_component(history),
        churn_component,
    )
    score = sum(component.score * component.weight for component in components)
    return HealthReport(
        repo_path=scan.repo_path,
        generated_at=datetime.now(timezone.utc),
        score=score,
        grade=grade_for(score),
        components=components,
        risk_files=risk_files,
        scan=scan,
        complexity=complexity,
        history=history,
        coverage=coverage,
    )


def _complexity_component(report: ComplexityReport) -> ComponentScore:
    """Share of analyzed Python files ranked A or B; 100 without files."""
    total = report.analyzed_file_count
    if total == 0:
        return ComponentScore("Complexity", 100.0, COMPLEXITY_WEIGHT, "no Python files analyzed")
    healthy = sum(1 for file in report.files if file.rank in HEALTHY_RANKS)
    return ComponentScore(
        name="Complexity",
        score=100.0 * healthy / total,
        weight=COMPLEXITY_WEIGHT,
        detail=f"{total - healthy} of {total} files rank C or worse",
    )


def _coverage_component(report: CoverageGapReport) -> ComponentScore:
    """The test pairing ratio scaled to 0-100."""
    if report.source_file_count == 0:
        detail = "no Python source files to analyze"
    else:
        detail = (
            f"{report.tested_count} of {report.source_file_count} source files have a matching test"
        )
    return ComponentScore(
        name="Coverage",
        score=100.0 * report.coverage_ratio,
        weight=COVERAGE_WEIGHT,
        detail=detail,
    )


def _bus_factor_component(report: HistoryReport) -> ComponentScore:
    """Knowledge concentration risk derived from the bus factor."""
    detail = (
        "no history to analyze"
        if report.analyzed_commit_count == 0
        else f"bus factor {report.bus_factor}"
    )
    return ComponentScore(
        name="Bus factor",
        score=bus_factor_score(report.bus_factor),
        weight=BUS_FACTOR_WEIGHT,
        detail=detail,
    )


def _churn_risk(
    history: HistoryReport, complexity: ComplexityReport
) -> tuple[ComponentScore, tuple[RiskFile, ...]]:
    """Score the overlap between hot files and complex files.

    A ``.py`` file is hot when its change count is at least half of the
    highest change count among ``.py`` files; it is complex when ranked
    C or worse. The risk files are the intersection of both sets.
    """
    python_churn = [churn for churn in history.hotspots if churn.path.suffix.lower() == ".py"]
    if not python_churn:
        return (
            ComponentScore("Churn risk", 100.0, CHURN_RISK_WEIGHT, "no Python files with churn"),
            (),
        )

    max_change_count = max(churn.change_count for churn in python_churn)
    hot = [churn for churn in python_churn if churn.change_count >= max_change_count / 2]
    complex_by_path = {
        file.path.as_posix(): file for file in complexity.files if file.rank not in HEALTHY_RANKS
    }
    risk_files = []
    for churn in hot:  # hotspots are already sorted by change count descending
        file = complex_by_path.get(churn.path.as_posix())
        if file is not None:
            risk_files.append(
                RiskFile(
                    path=churn.path,
                    change_count=churn.change_count,
                    max_complexity=file.max_complexity,
                    rank=file.rank,
                )
            )
    component = ComponentScore(
        name="Churn risk",
        score=100.0 * (1 - len(risk_files) / len(hot)),
        weight=CHURN_RISK_WEIGHT,
        detail=f"{len(risk_files)} of {len(hot)} hot files are also complex",
    )
    return component, tuple(risk_files)
