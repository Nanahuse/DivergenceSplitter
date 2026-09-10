"""YAML Scenario loading.

The YAML format defines one Scenario per file. It uses ``type`` discriminators
for conditions and detectors, human-readable time expressions for durations,
and file paths for reference images. YAML anchors/aliases are resolved by the
standard YAML loader before objects are built, so no custom reference mechanism
is used.

Only the condition and detector types whose field names are currently specified
are implemented. Referencing any other type produces a clear ``ValueError``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2
import yaml
from divergencesplitter.condition.detected import Detected
from divergencesplitter.condition.interface import Condition
from divergencesplitter.condition.then import Then
from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.detector.models import (
    FrozenConfigImage,
    Region,
    freeze_config_image,
)
from divergencesplitter.detector.root_mean_square_similarity import (
    RootMeanSquareSimilarityConfig,
    RootMeanSquareSimilarityDetector,
)
from divergencesplitter.detector.template_match import (
    TemplateMatchConfig,
    TemplateMatchDetector,
)
from divergencesplitter.rule import Action, Rule
from divergencesplitter.scenario.models import Scenario

_UNSUPPORTED_CONDITION_TYPES = (
    "elapsed",
    "all",
    "any",
    "not",
    "hold",
    "once",
    "nth",
    "reset_when",
    "rising_edge",
    "falling_edge",
)

_UNSUPPORTED_DETECTOR_TYPES = (
    "color_range",
    "mean_brightness",
    "phase_correlation",
    "difference_hash_similarity",
)

_TIME_PATTERN = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s)$")

_NANOSECONDS_PER_MILLISECOND = 1_000_000
_NANOSECONDS_PER_SECOND = 1_000_000_000


class ScenarioYamlError(Exception):
    """A YAML scenario could not be read or parsed."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__(str(error))


class ScenarioYamlValidationError(Exception):
    """Parsed YAML does not match the scenario schema."""


def load_scenario_yaml(path: str | Path) -> Scenario:
    """Load one Scenario from a YAML scenario file."""

    resolved = Path(path)
    try:
        with resolved.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ScenarioYamlError(error) from error

    try:
        return _scenario(value, resolved)
    except (TypeError, ValueError) as error:
        raise ScenarioYamlValidationError(str(error)) from error


def _scenario(value: object, path: Path) -> Scenario:
    root = _mapping(value, "scenario")
    _keys(
        root,
        required={"start_condition", "reset_condition", "splits"},
        optional={"incomplete_condition"},
    )
    start_condition = _condition_value(root["start_condition"], "start_condition", path)
    reset_condition = _condition_value(root["reset_condition"], "reset_condition", path)
    incomplete_condition = (
        _condition_value(root["incomplete_condition"], "incomplete_condition", path)
        if "incomplete_condition" in root
        else None
    )
    splits = _splits(root["splits"], path)
    return Scenario(start_condition, reset_condition, incomplete_condition, splits)


def _splits(
    value: object,
    path: Path,
) -> tuple[tuple[Rule, ...] | None, ...]:
    items = _list(value, "splits")
    return tuple(_split(item, path) for item in items)


def _split(value: object, path: Path) -> tuple[Rule, ...] | None:
    if value is None:
        return None
    split = _mapping(value, "split")
    _keys(split, required={"rules"})
    rules = _list(split["rules"], "split.rules")
    return tuple(_rule(item, path) for item in rules)


def _rule(value: object, path: Path) -> Rule:
    rule = _mapping(value, "rule")
    _keys(rule, required={"condition", "action"})
    condition = _condition_value(rule["condition"], "rule.condition", path)
    action = Action(_string(rule["action"], "rule.action"))
    return Rule(condition, action)


def _condition_list(
    value: object,
    field: str,
    path: Path,
) -> tuple[Condition, ...]:
    items = _list(value, field)
    return tuple(_condition_value(item, field, path) for item in items)


def _condition_value(value: object, field: str, path: Path) -> Condition:
    condition = _mapping(value, field)
    if "type" not in condition:
        raise ValueError(f"{field}.type is missing")
    condition_type = _string(condition["type"], f"{field}.type")
    match condition_type:
        case "detected":
            _keys(condition, required={"type", "minimum_score", "detector"})
            minimum_score = _number(
                condition["minimum_score"], f"{field}.minimum_score"
            )
            detector = _detector(condition["detector"], f"{field}.detector", path)
            return Detected(detector, minimum_score)
        case "then":
            _keys(condition, required={"type", "within", "conditions"})
            within_nanoseconds = _duration(condition["within"], f"{field}.within")
            children = _condition_list(
                condition["conditions"],
                f"{field}.conditions",
                path,
            )
            return Then(*children, within_nanoseconds=within_nanoseconds)
        case _ if condition_type in _UNSUPPORTED_CONDITION_TYPES:
            raise ValueError(
                f"condition type {condition_type!r} is not yet supported in YAML"
            )
        case _:
            raise ValueError(f"unsupported condition type: {condition_type!r}")


def _detector(
    value: object,
    field: str,
    path: Path,
) -> ImageDetector:
    detector = _mapping(value, field)
    if "type" not in detector:
        raise ValueError(f"{field}.type is missing")
    detector_type = _string(detector["type"], f"{field}.type")
    match detector_type:
        case "template_match":
            _keys(detector, required={"type", "reference"}, optional={"roi"})
            reference = _reference_image(
                detector["reference"],
                f"{field}.reference",
                path,
            )
            return TemplateMatchDetector(
                TemplateMatchConfig(
                    reference, _roi(detector.get("roi"), f"{field}.roi")
                )
            )
        case "mean_absolute_similarity":
            _keys(detector, required={"type", "reference"}, optional={"roi"})
            from divergencesplitter.detector.mean_absolute_similarity import (
                MeanAbsoluteSimilarityConfig,
                MeanAbsoluteSimilarityDetector,
            )

            return MeanAbsoluteSimilarityDetector(
                MeanAbsoluteSimilarityConfig(
                    _reference_image(detector["reference"], f"{field}.reference", path),
                    _roi(detector.get("roi"), f"{field}.roi"),
                )
            )
        case "root_mean_square_similarity":
            _keys(detector, required={"type", "reference"}, optional={"roi"})
            return RootMeanSquareSimilarityDetector(
                RootMeanSquareSimilarityConfig(
                    _reference_image(detector["reference"], f"{field}.reference", path),
                    _roi(detector.get("roi"), f"{field}.roi"),
                )
            )
        case _ if detector_type in _UNSUPPORTED_DETECTOR_TYPES:
            raise ValueError(
                f"detector type {detector_type!r} is not yet supported in YAML"
            )
        case _:
            raise ValueError(f"unsupported detector type: {detector_type!r}")


def _reference_image(
    value: object,
    field: str,
    path: Path,
) -> FrozenConfigImage:
    reference_path = _string(value, field)
    resolved = _resolve_path(reference_path, path.parent)
    image = cv2.imread(str(resolved), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"{field} could not be read as an image: {reference_path!r}")
    return freeze_config_image(image.tolist())


def _roi(value: object, field: str) -> Region | None:
    if value is None:
        return None
    mapping = _mapping(value, field)
    _keys(mapping, required={"x", "y", "width", "height"})
    return Region(
        _integer(mapping["x"], f"{field}.x"),
        _integer(mapping["y"], f"{field}.y"),
        _integer(mapping["width"], f"{field}.width"),
        _integer(mapping["height"], f"{field}.height"),
    )


def _duration(value: object, field: str) -> int:
    text = _string(value, field)
    match = _TIME_PATTERN.match(text)
    if match is None:
        raise ValueError(
            f"{field} must be a duration like '500ms' or '3s', got {text!r}"
        )
    amount = float(match.group("value"))
    unit = match.group("unit")
    units = {
        "ms": _NANOSECONDS_PER_MILLISECOND,
        "s": _NANOSECONDS_PER_SECOND,
    }
    if unit not in units:
        raise ValueError(f"{field} has an unknown time unit: {unit!r}")
    return int(amount * units[unit])


def _resolve_path(reference: str, base_directory: Path) -> Path:
    candidate = Path(reference)
    if candidate.is_absolute():
        return candidate
    return base_directory / candidate


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a mapping")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    return float(value)


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    return value


def _keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ValueError(f"missing scenario fields: {sorted(missing)!r}")
    if unknown:
        raise ValueError(f"unknown scenario fields: {sorted(unknown)!r}")
