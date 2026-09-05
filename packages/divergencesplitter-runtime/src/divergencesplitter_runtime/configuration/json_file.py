"""Strict JSON configuration loading."""

import json
from pathlib import Path
from typing import NoReturn

from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraDeviceConfiguration,
    CameraSourceConfiguration,
    RuntimeConfiguration,
    ScenarioConfiguration,
    SourceConfiguration,
    VideoSourceConfiguration,
)


class ConfigurationFileError(Exception):
    """A configuration file could not be read or parsed."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__(str(error))


class ConfigurationValidationError(Exception):
    """Parsed JSON does not match the configuration schema."""


def load_configuration(path: str | Path) -> ApplicationConfiguration:
    """Load one versioned DivergenceSplitter configuration file."""

    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = json.load(
                stream,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ConfigurationFileError(error) from error

    try:
        root = _object(value, "configuration")
        _keys(root, required={"version", "source", "scenario", "runtime"})
        version = _integer(root["version"], "version")
        source = _source(root["source"])
        scenario = _scenario(root["scenario"])
        runtime = _runtime(root["runtime"])
        return ApplicationConfiguration(version, source, scenario, runtime)
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationValidationError(str(error)) from error


def _source(value: object) -> SourceConfiguration:
    source = _object(value, "source")
    source_type = _string(source.get("type"), "source.type")
    if source_type == "camera":
        _keys(
            source,
            required={"type", "device", "width", "height", "fps"},
        )
        device_value = _object(source["device"], "source.device")
        _keys(device_value, required={"name", "id"})
        device = CameraDeviceConfiguration(
            _string(device_value["name"], "source.device.name"),
            _integer(device_value["id"], "source.device.id"),
        )
        return CameraSourceConfiguration(
            device,
            _integer(source["width"], "source.width"),
            _integer(source["height"], "source.height"),
            _number(source["fps"], "source.fps"),
        )
    if source_type == "video":
        _keys(source, required={"type", "path"})
        return VideoSourceConfiguration(_string(source["path"], "source.path"))
    raise ValueError(f"unsupported source type: {source_type!r}")


def _scenario(value: object) -> ScenarioConfiguration:
    scenario = _object(value, "scenario")
    _keys(scenario, required={"script"})
    return ScenarioConfiguration(_string(scenario["script"], "scenario.script"))


def _runtime(value: object) -> RuntimeConfiguration:
    runtime = _object(value, "runtime")
    _keys(runtime, required={"log_level"})
    return RuntimeConfiguration(_string(runtime["log_level"], "runtime.log_level"))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be an object")
    return value


def _keys(value: dict[str, object], *, required: set[str]) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required
    if missing:
        raise ValueError(f"missing configuration fields: {sorted(missing)!r}")
    if unknown:
        raise ValueError(f"unknown configuration fields: {sorted(unknown)!r}")


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    return value


def _integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{path} must be an integer")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{path} must be a number")
    return float(value)
