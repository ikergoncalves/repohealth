"""Tests for :mod:`repohealth.core.health`."""

from pathlib import Path

import pytest
from git import Actor, Repo

from repohealth.core.health import (
    BUS_FACTOR_WEIGHT,
    CHURN_RISK_WEIGHT,
    COMPLEXITY_WEIGHT,
    COVERAGE_WEIGHT,
    ComponentScore,
    HealthReport,
    build_health_report,
    bus_factor_score,
    grade_for,
)

_AUTHOR_A = Actor("Alice Dev", "alice@example.com")
_AUTHOR_B = Actor("Bob Dev", "bob@example.com")


def _complex_source(marker: int) -> str:
    """A module whose single function has cyclomatic complexity 11 (rank C)."""
    branches = "\n".join(f"    if value == {i}:\n        return {i}" for i in range(10))
    return f"def dispatch(value):\n{branches}\n    return {marker}\n"


def _write(root: Path, name: str, content: str) -> None:
    (root / name).write_text(content, encoding="utf-8")


def _commit(repo: Repo, message: str, author: Actor, day: int, add: list[str]) -> None:
    """Commit staged changes with a deterministic date in January 2024."""
    repo.index.add(add)
    date = f"2024-01-{day:02d}T12:00:00"
    repo.index.commit(message, author=author, committer=author, author_date=date, commit_date=date)


@pytest.fixture(scope="module")
def health_report(tmp_path_factory: pytest.TempPathFactory) -> HealthReport:
    """Report of a repository engineered to exercise every component.

    Files (all committed on day 1 by Alice):
    - ``engine.py``   — complex (rank C) and hot: modified on days 2-4.
    - ``cold.py``     — complex (rank C) but committed only once.
    - ``simple.py``   — simple (rank A) but hot: modified on days 5-6;
      paired with ``tests/test_simple.py`` for coverage.

    Expected numbers:
    - complexity: 2 of 4 analyzed files rank A/B          -> 50.0
    - coverage:   1 of 3 source files tested              -> 100/3
    - bus factor: Alice has 6 of 9 changes -> bus factor 1 -> 30.0
    - churn: hot = {engine.py (4), simple.py (3)}; risk = {engine.py} -> 50.0
    """
    root = tmp_path_factory.mktemp("health_repo")
    with Repo.init(root) as repo:
        (root / "tests").mkdir()
        _write(root, "engine.py", _complex_source(0))
        _write(root, "cold.py", _complex_source(99))
        _write(root, "simple.py", "VERSION = 1\n")
        _write(root, "tests/test_simple.py", "def test_simple():\n    assert True\n")
        _commit(
            repo,
            "add initial files",
            _AUTHOR_A,
            day=1,
            add=["engine.py", "cold.py", "simple.py", "tests/test_simple.py"],
        )

        for day, author in ((2, _AUTHOR_A), (3, _AUTHOR_B), (4, _AUTHOR_B)):
            _write(root, "engine.py", _complex_source(day))
            _commit(repo, f"tweak engine day {day}", author, day=day, add=["engine.py"])

        for day, author in ((5, _AUTHOR_A), (6, _AUTHOR_B)):
            _write(root, "simple.py", f"VERSION = {day}\n")
            _commit(repo, f"bump simple day {day}", author, day=day, add=["simple.py"])
    return build_health_report(root)


def _component(report: HealthReport, name: str) -> ComponentScore:
    return next(component for component in report.components if component.name == name)


def test_complexity_component_counts_healthy_ranks(health_report: HealthReport) -> None:
    component = _component(health_report, "Complexity")

    # simple.py and tests/test_simple.py rank A; engine.py and cold.py rank C.
    assert component.score == pytest.approx(100 * 2 / 4)
    assert component.weight == COMPLEXITY_WEIGHT
    assert component.detail == "2 of 4 files rank C or worse"


def test_coverage_component_scales_ratio(health_report: HealthReport) -> None:
    component = _component(health_report, "Coverage")

    # Sources: engine.py, cold.py, simple.py; only simple.py has a test.
    assert component.score == pytest.approx(100 * 1 / 3)
    assert component.weight == COVERAGE_WEIGHT
    assert component.detail == "1 of 3 source files have a matching test"


def test_bus_factor_component_penalizes_single_author(health_report: HealthReport) -> None:
    component = _component(health_report, "Bus factor")

    # Alice: 4 (day 1) + 1 (day 2) + 1 (day 5) = 6 of 9 changes -> bus factor 1.
    assert health_report.history.bus_factor == 1
    assert component.score == pytest.approx(30.0)
    assert component.weight == BUS_FACTOR_WEIGHT


def test_churn_risk_component_scores_hot_and_complex_overlap(
    health_report: HealthReport,
) -> None:
    component = _component(health_report, "Churn risk")

    # Hot (change_count >= 4 / 2): engine.py (4) and simple.py (3);
    # only engine.py is also complex -> 100 * (1 - 1/2).
    assert component.score == pytest.approx(50.0)
    assert component.weight == CHURN_RISK_WEIGHT
    assert component.detail == "1 of 2 hot files are also complex"


def test_score_is_the_weighted_sum_of_components(health_report: HealthReport) -> None:
    expected = 0.30 * 50.0 + 0.25 * (100 / 3) + 0.20 * 30.0 + 0.25 * 50.0

    assert health_report.score == pytest.approx(expected)
    assert health_report.grade == "E"
    assert sum(component.weight for component in health_report.components) == pytest.approx(1.0)


def test_risk_files_contains_only_hot_and_complex_files(health_report: HealthReport) -> None:
    paths = [risk.path.as_posix() for risk in health_report.risk_files]

    assert paths == ["engine.py"]  # hot-but-simple and complex-but-cold excluded

    risk = health_report.risk_files[0]
    assert risk.change_count == 4
    assert risk.max_complexity == 11
    assert risk.rank == "C"


@pytest.mark.parametrize(
    ("score", "grade"),
    [
        (100, "A"),
        (90, "A"),
        (89.99, "B"),
        (80, "B"),
        (79.99, "C"),
        (65, "C"),
        (64.99, "D"),
        (50, "D"),
        (49.99, "E"),
        (35, "E"),
        (34.99, "F"),
        (0, "F"),
    ],
)
def test_grade_boundaries(score: float, grade: str) -> None:
    assert grade_for(score) == grade


@pytest.mark.parametrize(
    ("bus_factor", "score"),
    [(0, 100.0), (1, 30.0), (2, 70.0), (3, 100.0), (10, 100.0)],
)
def test_bus_factor_score(bus_factor: int, score: float) -> None:
    assert bus_factor_score(bus_factor) == pytest.approx(score)


def test_empty_repository_produces_neutral_report(tmp_path: Path) -> None:
    with Repo.init(tmp_path):
        pass

    report = build_health_report(tmp_path)

    assert report.score == pytest.approx(100.0)
    assert report.grade == "A"
    assert report.risk_files == ()
    assert [component.score for component in report.components] == [100.0] * 4
