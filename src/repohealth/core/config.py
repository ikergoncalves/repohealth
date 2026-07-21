"""Project configuration for repohealth.

This module holds the pure, testable core of the configuration support:
it discovers and loads the configuration from ``.repohealth.toml`` at the
repository root or from a ``[tool.repohealth]`` section in
``pyproject.toml``, validates it, and builds gitignore-style exclude
matchers with pathspec.
"""

import difflib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from pathspec import PathSpec

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

WEIGHT_KEYS = ("complexity", "coverage", "bus_factor", "churn_risk")
DEFAULT_WEIGHTS = {
    "complexity": 0.30,
    "coverage": 0.25,
    "bus_factor": 0.20,
    "churn_risk": 0.25,
}
VALID_KEYS = ("weights", "exclude", "min_score", "complexity_threshold")
_RANKS = "ABCDEF"
_WEIGHT_SUM_TOLERANCE = 1e-6

SOURCE_DEFAULTS = "defaults"
SOURCE_REPOHEALTH_TOML = ".repohealth.toml"
SOURCE_PYPROJECT = "pyproject.toml"


class ConfigError(Exception):
    """Raised when a configuration file cannot be read or is invalid."""


@dataclass(frozen=True)
class RepohealthConfig:
    """Effective repohealth configuration.

    ``source`` records where the values came from: ``"defaults"``,
    ``".repohealth.toml"`` or ``"pyproject.toml"``.
    """

    weights: dict[str, float]
    exclude: tuple[str, ...]
    min_score: float | None
    complexity_threshold: str | None
    source: str = SOURCE_DEFAULTS

    @classmethod
    def default(cls) -> "RepohealthConfig":
        """The built-in configuration used when no file is found."""
        return cls(
            weights=dict(DEFAULT_WEIGHTS),
            exclude=(),
            min_score=None,
            complexity_threshold=None,
        )


def load_config(repo_root: str | Path) -> RepohealthConfig:
    """Discover and load the configuration for a repository.

    The first source found wins: ``.repohealth.toml`` at the repository
    root (the file's root table is the configuration), then the
    ``[tool.repohealth]`` section of ``pyproject.toml``, then the
    built-in defaults. Keys absent from the file inherit their default
    value; ``weights`` is all-or-nothing (either the full table with the
    four keys or absent).

    Args:
        repo_root: Root directory of the repository.

    Returns:
        The validated effective configuration.

    Raises:
        ConfigError: If a configuration file cannot be parsed or fails
            validation.
    """
    root = Path(repo_root)
    repohealth_toml = root / ".repohealth.toml"
    if repohealth_toml.is_file():
        return _build_config(_read_toml(repohealth_toml), repohealth_toml, SOURCE_REPOHEALTH_TOML)

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        tool = _read_toml(pyproject).get("tool")
        section = tool.get("repohealth") if isinstance(tool, dict) else None
        if section is not None:
            if not isinstance(section, dict):
                raise ConfigError(f"{pyproject}: [tool.repohealth] must be a table")
            return _build_config(section, pyproject, SOURCE_PYPROJECT)

    return RepohealthConfig.default()


def build_exclude_matcher(patterns: Iterable[str]) -> Callable[[Path], bool]:
    """Build a matcher for gitignore-style exclude patterns.

    The returned callable expects paths relative to the repository root
    and matches them in POSIX form, so it works identically on every
    platform.
    """
    spec = PathSpec.from_lines("gitignore", patterns)

    def matches(path: Path) -> bool:
        return spec.match_file(path.as_posix())

    return matches


def _read_toml(path: Path) -> dict:
    """Parse a TOML file, translating failures into :class:`ConfigError`.

    Decoded as UTF-8 with an optional BOM, which Windows editors love to
    prepend and :func:`tomllib.load` would otherwise reject.
    """
    try:
        return tomllib.loads(path.read_bytes().decode("utf-8-sig"))
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}: not valid UTF-8: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc


def _build_config(data: dict, path: Path, source: str) -> RepohealthConfig:
    """Validate a raw configuration table and merge it over the defaults."""
    _reject_unknown_keys(data, path)
    default = RepohealthConfig.default()
    return RepohealthConfig(
        weights=_parse_weights(data, path) or dict(default.weights),
        exclude=_parse_exclude(data, path) if "exclude" in data else default.exclude,
        min_score=_parse_min_score(data, path),
        complexity_threshold=_parse_complexity_threshold(data, path),
        source=source,
    )


def _reject_unknown_keys(data: dict, path: Path) -> None:
    """Fail fast on unknown keys, suggesting the closest valid one."""
    unknown = sorted(set(data) - set(VALID_KEYS))
    if not unknown:
        return
    hints = []
    for key in unknown:
        close = difflib.get_close_matches(str(key), VALID_KEYS, n=1)
        hints.append(f"'{key}' (did you mean '{close[0]}'?)" if close else f"'{key}'")
    raise ConfigError(
        f"{path}: unknown key(s): {', '.join(hints)}; valid keys are: {', '.join(VALID_KEYS)}"
    )


def _parse_weights(data: dict, path: Path) -> dict[str, float] | None:
    """Validate the all-or-nothing ``weights`` table."""
    if "weights" not in data:
        return None
    raw = data["weights"]
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: 'weights' must be a table")
    if set(raw) != set(WEIGHT_KEYS):
        got = ", ".join(sorted(str(key) for key in raw)) or "none"
        raise ConfigError(
            f"{path}: 'weights' must define exactly the keys {', '.join(WEIGHT_KEYS)} (got: {got})"
        )
    weights: dict[str, float] = {}
    for key in WEIGHT_KEYS:
        value = raw[key]
        if not _is_number(value) or value < 0:
            raise ConfigError(f"{path}: 'weights.{key}' must be a number >= 0 (got: {value!r})")
        weights[key] = float(value)
    total = sum(weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise ConfigError(f"{path}: 'weights' must sum to 1.0 (got: {total})")
    return weights


def _parse_exclude(data: dict, path: Path) -> tuple[str, ...]:
    """Validate ``exclude`` as a list of pattern strings."""
    raw = data["exclude"]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ConfigError(f"{path}: 'exclude' must be a list of strings (got: {raw!r})")
    return tuple(raw)


def _parse_min_score(data: dict, path: Path) -> float | None:
    """Validate ``min_score`` as a number in the 0-100 range."""
    if "min_score" not in data:
        return None
    raw = data["min_score"]
    if not _is_number(raw) or not 0 <= raw <= 100:
        raise ConfigError(f"{path}: 'min_score' must be a number between 0 and 100 (got: {raw!r})")
    return float(raw)


def _parse_complexity_threshold(data: dict, path: Path) -> str | None:
    """Validate ``complexity_threshold`` as a single A-F rank letter."""
    if "complexity_threshold" not in data:
        return None
    raw = data["complexity_threshold"]
    if not isinstance(raw, str) or raw.upper() not in _RANKS or len(raw) != 1:
        raise ConfigError(
            f"{path}: 'complexity_threshold' must be a single rank letter from A to F "
            f"(got: {raw!r})"
        )
    return raw.upper()


def _is_number(value: object) -> bool:
    """Whether a TOML value is a real number (booleans are not)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)
