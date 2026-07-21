"""Tests for :mod:`repohealth.core.config` and the configuration integration."""

import json
from pathlib import Path

import pytest
from git import Actor, Repo
from typer.testing import CliRunner

from repohealth.cli import app
from repohealth.core.config import (
    ConfigError,
    RepohealthConfig,
    build_exclude_matcher,
    load_config,
)
from repohealth.core.health import (
    BUS_FACTOR_WEIGHT,
    CHURN_RISK_WEIGHT,
    COMPLEXITY_WEIGHT,
    COVERAGE_WEIGHT,
    build_health_report,
)
from repohealth.core.history import analyze_history
from repohealth.core.repo_scanner import scan_repository

runner = CliRunner()

_AUTHOR_A = Actor("Alice Dev", "alice@example.com")
_AUTHOR_B = Actor("Bob Dev", "bob@example.com")

_CUSTOM_WEIGHTS_TOML = """\
exclude = ["docs/"]

[weights]
complexity = 0.6
coverage = 0.2
bus_factor = 0.1
churn_risk = 0.1
"""


def _complex_source(marker: int) -> str:
    """A module whose single function has cyclomatic complexity 11 (rank C)."""
    branches = "\n".join(f"    if value == {i}:\n        return {i}" for i in range(10))
    return f"def dispatch(value):\n{branches}\n    return {marker}\n"


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Repo, message: str, author: Actor, day: int, add: list[str]) -> None:
    """Commit staged changes with a deterministic date in January 2024."""
    repo.index.add(add)
    date = f"2024-01-{day:02d}T12:00:00"
    repo.index.commit(message, author=author, committer=author, author_date=date, commit_date=date)


def _make_repo(root: Path) -> None:
    """A repository where ``docs/notes.md`` is Bob's only contribution.

    - ``engine.py``  — complex (rank C), no matching test.
    - ``simple.py``  — simple (rank A), paired with ``tests/test_simple.py``.
    - ``docs/notes.md`` — committed by Alice, then modified by Bob on
      days 2-4, so excluding ``docs/`` erases Bob from the history.
    """
    with Repo.init(root) as repo:
        _write(root, "engine.py", _complex_source(0))
        _write(root, "simple.py", "VERSION = 1\n")
        _write(root, "tests/test_simple.py", "def test_simple():\n    assert True\n")
        _write(root, "docs/notes.md", "# notes\n")
        _commit(
            repo,
            "add initial files",
            _AUTHOR_A,
            day=1,
            add=["engine.py", "simple.py", "tests/test_simple.py", "docs/notes.md"],
        )
        for day in (2, 3, 4):
            _write(root, "docs/notes.md", f"# notes day {day}\n")
            _commit(repo, f"update notes day {day}", _AUTHOR_B, day=day, add=["docs/notes.md"])


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _make_repo(tmp_path)
    return tmp_path


# --- defaults and discovery -------------------------------------------------


def test_default_matches_historical_weights() -> None:
    config = RepohealthConfig.default()

    assert config.weights == {
        "complexity": COMPLEXITY_WEIGHT,
        "coverage": COVERAGE_WEIGHT,
        "bus_factor": BUS_FACTOR_WEIGHT,
        "churn_risk": CHURN_RISK_WEIGHT,
    }
    assert config.exclude == ()
    assert config.min_score is None
    assert config.complexity_threshold is None
    assert config.source == "defaults"


def test_load_config_without_files_returns_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path) == RepohealthConfig.default()


def test_load_config_reads_repohealth_toml(tmp_path: Path) -> None:
    _write(tmp_path, ".repohealth.toml", _CUSTOM_WEIGHTS_TOML)

    config = load_config(tmp_path)

    assert config.weights == {
        "complexity": 0.6,
        "coverage": 0.2,
        "bus_factor": 0.1,
        "churn_risk": 0.1,
    }
    assert config.exclude == ("docs/",)
    assert config.source == ".repohealth.toml"


def test_load_config_reads_pyproject_tool_section(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.repohealth]\nexclude = ["*.md"]\nmin_score = 80\ncomplexity_threshold = "c"\n',
    )

    config = load_config(tmp_path)

    assert config.exclude == ("*.md",)
    assert config.min_score == 80.0
    assert config.complexity_threshold == "C"  # normalized to upper case
    assert config.source == "pyproject.toml"


def test_load_config_ignores_pyproject_without_tool_section(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\n')

    assert load_config(tmp_path) == RepohealthConfig.default()


def test_repohealth_toml_wins_over_pyproject(tmp_path: Path) -> None:
    _write(tmp_path, ".repohealth.toml", 'exclude = ["from-toml/"]\n')
    _write(tmp_path, "pyproject.toml", '[tool.repohealth]\nexclude = ["from-pyproject/"]\n')

    config = load_config(tmp_path)

    assert config.exclude == ("from-toml/",)
    assert config.source == ".repohealth.toml"


def test_partial_config_inherits_defaults(tmp_path: Path) -> None:
    _write(tmp_path, ".repohealth.toml", "min_score = 70\n")

    config = load_config(tmp_path)

    assert config.min_score == 70.0
    assert config.weights == RepohealthConfig.default().weights
    assert config.exclude == ()
    assert config.complexity_threshold is None


# --- validation errors ------------------------------------------------------


def _error_for(tmp_path: Path, content: str) -> str:
    _write(tmp_path, ".repohealth.toml", content)
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    return str(excinfo.value)


def test_unknown_key_is_rejected_with_suggestion(tmp_path: Path) -> None:
    message = _error_for(tmp_path, "min_socre = 70\n")

    assert ".repohealth.toml" in message
    assert "min_socre" in message
    assert "did you mean 'min_score'?" in message


def test_unknown_key_without_close_match_lists_valid_keys(tmp_path: Path) -> None:
    message = _error_for(tmp_path, "zzz = 1\n")

    assert "'zzz'" in message
    assert "valid keys are: weights, exclude, min_score, complexity_threshold" in message


def test_incomplete_weights_are_rejected(tmp_path: Path) -> None:
    message = _error_for(tmp_path, "[weights]\ncomplexity = 1.0\n")

    assert "'weights' must define exactly the keys" in message
    assert "got: complexity" in message


def test_weights_not_summing_to_one_are_rejected(tmp_path: Path) -> None:
    message = _error_for(
        tmp_path,
        "[weights]\ncomplexity = 0.5\ncoverage = 0.5\nbus_factor = 0.5\nchurn_risk = 0.5\n",
    )

    assert "'weights' must sum to 1.0 (got: 2.0)" in message


def test_negative_weight_is_rejected(tmp_path: Path) -> None:
    message = _error_for(
        tmp_path,
        "[weights]\ncomplexity = -0.1\ncoverage = 0.5\nbus_factor = 0.3\nchurn_risk = 0.3\n",
    )

    assert "'weights.complexity' must be a number >= 0" in message


def test_weights_must_be_a_table(tmp_path: Path) -> None:
    assert "'weights' must be a table" in _error_for(tmp_path, "weights = 1\n")


def test_min_score_out_of_range_is_rejected(tmp_path: Path) -> None:
    message = _error_for(tmp_path, "min_score = 101\n")

    assert "'min_score' must be a number between 0 and 100" in message


def test_min_score_boolean_is_rejected(tmp_path: Path) -> None:
    assert "'min_score'" in _error_for(tmp_path, "min_score = true\n")


def test_invalid_complexity_threshold_is_rejected(tmp_path: Path) -> None:
    message = _error_for(tmp_path, 'complexity_threshold = "G"\n')

    assert "'complexity_threshold' must be a single rank letter from A to F" in message


def test_multicharacter_threshold_is_rejected(tmp_path: Path) -> None:
    assert "'complexity_threshold'" in _error_for(tmp_path, 'complexity_threshold = "AB"\n')


def test_exclude_must_be_a_list_of_strings(tmp_path: Path) -> None:
    assert "'exclude' must be a list of strings" in _error_for(tmp_path, "exclude = [1]\n")


def test_invalid_toml_is_reported_with_file_name(tmp_path: Path) -> None:
    message = _error_for(tmp_path, "not toml [[[")

    assert ".repohealth.toml" in message
    assert "invalid TOML" in message


def test_utf8_bom_is_tolerated(tmp_path: Path) -> None:
    (tmp_path / ".repohealth.toml").write_bytes(b"\xef\xbb\xbfmin_score = 70\n")

    assert load_config(tmp_path).min_score == 70.0


def test_non_utf8_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".repohealth.toml").write_bytes(b"\xff\xfe invalid")

    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_config(tmp_path)


# --- exclude matcher --------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("*.md", "README.md", True),
        ("*.md", "docs/guide.md", True),
        ("*.md", "docs/guide.rst", False),
        ("migrations/", "migrations/0001_init.py", True),
        ("migrations/", "app/migrations/0001_init.py", True),
        ("migrations/", "migrations_helper.py", False),
        ("src/legacy/**", "src/legacy/old.py", True),
        ("src/legacy/**", "src/legacy/deep/older.py", True),
        ("src/legacy/**", "src/modern/new.py", False),
    ],
)
def test_exclude_matcher_patterns(pattern: str, path: str, matches: bool) -> None:
    matcher = build_exclude_matcher((pattern,))

    assert matcher(Path(path)) is matches


# --- excludes applied to the analyses ---------------------------------------


def test_exclude_removes_files_from_scan(repo: Path) -> None:
    report = scan_repository(repo, exclude=("*.md",))

    assert all(stats.path.suffix != ".md" for stats in report.files)
    assert all(stats.language != "Other" for stats in report.languages)


def test_exclude_removes_files_end_to_end_from_history(repo: Path) -> None:
    baseline = analyze_history(repo)
    filtered = analyze_history(repo, exclude=("docs/",))

    # Baseline: docs/notes.md is the hottest file and Bob's only work.
    assert baseline.hotspots[0].path.as_posix() == "docs/notes.md"
    assert dict(baseline.author_totals) == {"Alice Dev": 4, "Bob Dev": 3}

    # Excluded: invisible in hotspots/ownership and in the author totals.
    hotspot_paths = {churn.path.as_posix() for churn in filtered.hotspots}
    ownership_paths = {ownership.path.as_posix() for ownership in filtered.ownership}
    assert "docs/notes.md" not in hotspot_paths
    assert "docs/notes.md" not in ownership_paths
    assert dict(filtered.author_totals) == {"Alice Dev": 3}
    assert filtered.total_changes == 3
    assert filtered.bus_factor_authors == ("Alice Dev",)


def test_exclude_removes_files_from_health_report(repo: Path) -> None:
    report = build_health_report(repo, exclude=("engine.py",))

    complexity_paths = {file.path.as_posix() for file in report.complexity.files}
    coverage_paths = {status.path.as_posix() for status in report.coverage.files}
    assert "engine.py" not in complexity_paths
    assert "engine.py" not in coverage_paths
    assert report.exclude == ("engine.py",)


def test_custom_weights_change_the_score_arithmetic(repo: Path) -> None:
    weights = {"complexity": 0.6, "coverage": 0.2, "bus_factor": 0.1, "churn_risk": 0.1}

    default = build_health_report(repo)
    custom = build_health_report(repo, weights=weights)

    by_name = {component.name: component for component in custom.components}
    assert by_name["Complexity"].weight == 0.6
    assert by_name["Coverage"].weight == 0.2
    assert by_name["Bus factor"].weight == 0.1
    assert by_name["Churn risk"].weight == 0.1

    # Component scores are weight-independent; only the weighting changes.
    expected = sum(
        component.score * weights[key]
        for component, key in zip(
            default.components, ("complexity", "coverage", "bus_factor", "churn_risk"), strict=True
        )
    )
    assert custom.score == pytest.approx(expected)
    assert custom.score != pytest.approx(default.score)


# --- CLI integration --------------------------------------------------------


def test_cli_report_reflects_config_excludes_and_weights(repo: Path) -> None:
    _write(repo, ".repohealth.toml", _CUSTOM_WEIGHTS_TOML)

    result = runner.invoke(app, ["report", str(repo), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["config"] == {
        "source": ".repohealth.toml",
        "weights": {"complexity": 0.6, "coverage": 0.2, "bus_factor": 0.1, "churn_risk": 0.1},
        "exclude": ["docs/"],
    }
    hotspot_paths = {entry["path"] for entry in payload["history"]["hotspots"]}
    assert "docs/notes.md" not in hotspot_paths
    weights = {component["name"]: component["weight"] for component in payload["components"]}
    assert weights["Complexity"] == 0.6


def test_cli_no_config_ignores_the_config_file(repo: Path) -> None:
    _write(repo, ".repohealth.toml", _CUSTOM_WEIGHTS_TOML)

    result = runner.invoke(app, ["report", str(repo), "--format", "json", "--no-config"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["config"]["source"] == "defaults"
    assert payload["config"]["weights"]["complexity"] == COMPLEXITY_WEIGHT
    assert payload["config"]["exclude"] == []
    assert "docs/notes.md" in {entry["path"] for entry in payload["history"]["hotspots"]}


def test_cli_invalid_config_is_a_red_error(repo: Path) -> None:
    _write(repo, ".repohealth.toml", "min_socre = 70\n")

    result = runner.invoke(app, ["report", str(repo)])

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "min_socre" in result.output


def test_cli_min_score_flag_wins_over_config_file(repo: Path) -> None:
    _write(repo, ".repohealth.toml", "min_score = 100\n")

    gated = runner.invoke(app, ["report", str(repo)])
    overridden = runner.invoke(app, ["report", str(repo), "--min-score", "0"])

    assert gated.exit_code == 2
    assert "below the required minimum" in gated.output
    assert overridden.exit_code == 0


def test_cli_complexity_threshold_flag_wins_over_config_file(repo: Path) -> None:
    _write(repo, ".repohealth.toml", 'complexity_threshold = "A"\n')

    gated = runner.invoke(app, ["complexity", str(repo)])
    overridden = runner.invoke(app, ["complexity", str(repo), "--threshold", "F"])

    assert gated.exit_code == 2
    assert "threshold exceeded" in gated.output
    assert overridden.exit_code == 0
    assert "No files at or worse than rank F" in overridden.output


def test_cli_scan_applies_config_exclude(repo: Path) -> None:
    _write(repo, ".repohealth.toml", 'exclude = ["*.py", "docs/"]\n')

    result = runner.invoke(app, ["scan", str(repo)])

    assert result.exit_code == 0
    assert "Python" not in result.output
