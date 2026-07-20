"""Tests for :mod:`repohealth.core.exporters`."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from git import Actor, Repo

from repohealth import __version__
from repohealth.core.exporters import to_html, to_json, to_markdown
from repohealth.core.health import HealthReport, RiskFile, build_health_report

_EVIL_AUTHOR = Actor("Eve <evil> Dev", "eve@example.com")


def _write(root: Path, name: str, content: str) -> None:
    (root / name).write_text(content, encoding="utf-8")


def _commit(repo: Repo, message: str, day: int, add: list[str]) -> None:
    repo.index.add(add)
    date = f"2024-02-{day:02d}T12:00:00"
    repo.index.commit(
        message, author=_EVIL_AUTHOR, committer=_EVIL_AUTHOR, author_date=date, commit_date=date
    )


@pytest.fixture(scope="module")
def sample_report(tmp_path_factory: pytest.TempPathFactory) -> HealthReport:
    """Report of a small repository authored by ``Eve <evil> Dev``."""
    root = tmp_path_factory.mktemp("exporters_repo")
    with Repo.init(root) as repo:
        (root / "tests").mkdir()
        _write(root, "app.py", "def run():\n    return 1\n")
        _write(root, "util.py", "def helper():\n    return 2\n")
        _write(root, "tests/test_app.py", "def test_run():\n    assert True\n")
        _commit(
            repo, "add app, util and test", day=1, add=["app.py", "util.py", "tests/test_app.py"]
        )

        _write(root, "app.py", "def run():\n    return 2\n")
        _commit(repo, "tweak app", day=2, add=["app.py"])
    return build_health_report(root)


def test_to_json_round_trips_and_matches_report(sample_report: HealthReport) -> None:
    payload = json.loads(to_json(sample_report))

    for key in (
        "version",
        "generated_at",
        "score",
        "grade",
        "components",
        "risk_files",
        "scan",
        "complexity",
        "history",
        "coverage",
    ):
        assert key in payload

    assert payload["version"] == __version__
    assert payload["score"] == pytest.approx(sample_report.score, abs=0.01)
    assert payload["grade"] == sample_report.grade
    assert len(payload["components"]) == 4


def test_to_json_datetimes_are_iso_8601(sample_report: HealthReport) -> None:
    payload = json.loads(to_json(sample_report))

    assert datetime.fromisoformat(payload["generated_at"]) == sample_report.generated_at
    for hotspot in payload["history"]["hotspots"]:
        datetime.fromisoformat(hotspot["last_modified"])  # must parse


def test_to_json_paths_are_posix_strings(sample_report: HealthReport) -> None:
    payload = json.loads(to_json(sample_report))

    coverage_paths = {status["path"] for status in payload["coverage"]["files"]}

    assert {"app.py", "util.py"} == coverage_paths
    assert "tests/test_app.py" in {
        test for status in payload["coverage"]["files"] for test in status["matched_tests"]
    }


def test_to_markdown_contains_summary_and_sections(sample_report: HealthReport) -> None:
    markdown = to_markdown(sample_report)

    assert f"Score: {sample_report.score:.1f} / 100 — Grade {sample_report.grade}" in markdown
    for name in ("Complexity", "Coverage", "Bus factor", "Churn risk"):
        assert name in markdown
    assert "`app.py`" in markdown
    assert "`util.py`" in markdown  # listed among untested source files


def test_to_html_contains_score_and_grade(sample_report: HealthReport) -> None:
    html = to_html(sample_report)

    assert f"{sample_report.score:.1f}" in html
    assert 'class="badge" style="background:' in html
    assert f">{sample_report.grade}</span>" in html


def test_to_html_escapes_author_names(sample_report: HealthReport) -> None:
    html = to_html(sample_report)

    assert "&lt;evil&gt;" in html
    assert "<evil>" not in html


def test_to_html_escapes_risk_file_paths(sample_report: HealthReport) -> None:
    injected = replace(
        sample_report,
        risk_files=(RiskFile(path=Path("<evil>.py"), change_count=3, max_complexity=12, rank="C"),),
    )

    html = to_html(injected)

    assert "&lt;evil&gt;.py" in html
    assert "<evil>.py" not in html
