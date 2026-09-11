"""Strict JSON configuration loading."""

import json
from pathlib import Path
from typing import NoReturn, assert_never

from divergencesplitter.livesplit.models import LiveSplitConnection

from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    CropConfiguration,
    InstanceConfiguration,
    NdiSourceConfiguration,
    ResizeConfiguration,
    RuntimeConfiguration,
    SourceConfiguration,
    SourceTransformConfiguration,
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
        _keys(root, required={"version", "source", "instances", "runtime"})
        version = _integer(root["version"], "version")
        if version != 1:
            raise ValueError(f"unsupported configuration version: {version!r}")
        source = _source(root["source"])
        instances = _instances(root["instances"])
        runtime = _runtime(root["runtime"])
        return ApplicationConfiguration(version, source, instances, runtime)
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationValidationError(str(error)) from error


def save_configuration(
    path: str | Path,
    configuration: ApplicationConfiguration,
) -> None:
    """Write one versioned configuration as canonical JSON.

    The emitted document round-trips through :func:`load_configuration` to the
    same typed values. Camera device and mode values, video path,
    instance connection endpoints and scenario paths, and log level keep their
    configured meaning, and the ``source`` common field stays ``type``-only.
    """

    Path(path).write_text(_dump(configuration), encoding="utf-8")


def _dump(configuration: ApplicationConfiguration) -> str:
    return json.dumps(_as_dict(configuration), indent=2, ensure_ascii=False) + "\n"


def _as_dict(configuration: ApplicationConfiguration) -> dict[str, object]:
    return {
        "version": configuration.version,
        "source": _source_dict(configuration.source),
        "instances": [_instance_dict(instance) for instance in configuration.instances],
        "runtime": {"log_level": configuration.runtime.log_level},
    }


def _instance_dict(instance: InstanceConfiguration) -> dict[str, object]:
    return {
        "connection": {
            "rpc_endpoint": instance.connection.rpc_endpoint,
            "event_endpoint": instance.connection.event_endpoint,
        },
        "scenario": instance.scenario,
    }


def _source_dict(source: SourceConfiguration) -> dict[str, object]:
    if isinstance(source, CameraSourceConfiguration):
        return {
            "type": "camera",
            "device": {
                "backend": source.device.backend.value,
                "name": source.device.name,
                "index": source.device.index,
            },
            "mode": {
                "width": source.mode.width,
                "height": source.mode.height,
                "fps": source.mode.fps,
                "subtype_guid": source.mode.subtype_guid,
            },
            "request_60_fps": source.request_60_fps,
            "transform": _transform_dict(source.transform),
        }
    if isinstance(source, VideoSourceConfiguration):
        return {
            "type": "video",
            "path": source.path,
            "transform": _transform_dict(source.transform),
        }
    if isinstance(source, NdiSourceConfiguration):
        return {
            "type": "ndi",
            "name": source.name,
            "transform": _transform_dict(source.transform),
        }
    assert_never(source)


def _source(value: object) -> SourceConfiguration:
    source = _object(value, "source")
    source_type = _string(source.get("type"), "source.type")
    if source_type == "camera":
        _keys(
            source,
            required={"type", "device", "mode", "request_60_fps"},
            optional={"transform"},
        )
        device_value = _object(source["device"], "source.device")
        _keys(device_value, required={"backend", "name", "index"})
        device = CameraDeviceConfiguration(
            _enum(device_value["backend"], CameraBackend, "source.device.backend"),
            _string(device_value["name"], "source.device.name"),
            _integer(device_value["index"], "source.device.index"),
        )
        mode_value = _object(source["mode"], "source.mode")
        _keys(mode_value, required={"width", "height", "fps", "subtype_guid"})
        mode = CameraModeConfiguration(
            _integer(mode_value["width"], "source.mode.width"),
            _integer(mode_value["height"], "source.mode.height"),
            _number(mode_value["fps"], "source.mode.fps"),
            _string(mode_value["subtype_guid"], "source.mode.subtype_guid"),
        )
        return CameraSourceConfiguration(
            device,
            mode,
            _boolean(source["request_60_fps"], "source.request_60_fps"),
            _transform(source["transform"], "source.transform")
            if "transform" in source
            else SourceTransformConfiguration(),
        )
    if source_type == "video":
        _keys(source, required={"type", "path"}, optional={"transform"})
        return VideoSourceConfiguration(
            _string(source["path"], "source.path"),
            _transform(source["transform"], "source.transform")
            if "transform" in source
            else SourceTransformConfiguration(),
        )
    if source_type == "ndi":
        _keys(source, required={"type", "name"}, optional={"transform"})
        return NdiSourceConfiguration(
            _string(source["name"], "source.name"),
            _transform(source["transform"], "source.transform")
            if "transform" in source
            else SourceTransformConfiguration(),
        )
    raise ValueError(f"unsupported source type: {source_type!r}")


def _instances(value: object) -> tuple[InstanceConfiguration, ...]:
    instances = _array(value, "instances")
    return tuple(_instance(item, index) for index, item in enumerate(instances))


def _instance(value: object, index: int) -> InstanceConfiguration:
    prefix = f"instances[{index}]"
    instance = _object(value, prefix)
    _keys(instance, required={"connection", "scenario"})
    connection = _connection(instance["connection"], f"{prefix}.connection")
    scenario = _string(instance["scenario"], f"{prefix}.scenario")
    return InstanceConfiguration(connection, scenario)


def _connection(value: object, path: str) -> LiveSplitConnection:
    connection = _object(value, path)
    _keys(connection, required={"rpc_endpoint", "event_endpoint"})
    return LiveSplitConnection(
        _string(connection["rpc_endpoint"], f"{path}.rpc_endpoint"),
        _string(connection["event_endpoint"], f"{path}.event_endpoint"),
    )


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


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{path} must be an array")
    return value


def _transform_dict(transform: SourceTransformConfiguration) -> dict[str, object]:
    return {
        "crop": None
        if transform.crop is None
        else {
            "left": transform.crop.left,
            "right": transform.crop.right,
            "top": transform.crop.top,
            "bottom": transform.crop.bottom,
        },
        "resize": None
        if transform.resize is None
        else {"width": transform.resize.width, "height": transform.resize.height},
    }


def _transform(value: object, path: str) -> SourceTransformConfiguration:
    transform = _object(value, path)
    _keys(transform, required={"crop", "resize"})
    crop_value = transform["crop"]
    crop = None
    if crop_value is not None:
        crop_object = _object(crop_value, f"{path}.crop")
        _keys(crop_object, required={"left", "right", "top", "bottom"})
        crop = CropConfiguration(
            _integer(crop_object["left"], f"{path}.crop.left"),
            _integer(crop_object["right"], f"{path}.crop.right"),
            _integer(crop_object["top"], f"{path}.crop.top"),
            _integer(crop_object["bottom"], f"{path}.crop.bottom"),
        )
    resize_value = transform["resize"]
    resize = None
    if resize_value is not None:
        resize_object = _object(resize_value, f"{path}.resize")
        _keys(resize_object, required={"width", "height"})
        resize = ResizeConfiguration(
            _integer(resize_object["width"], f"{path}.resize.width"),
            _integer(resize_object["height"], f"{path}.resize.height"),
        )
    return SourceTransformConfiguration(crop, resize)


def _keys(
    value: dict[str, object],
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
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


def _boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{path} must be a boolean")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{path} must be a number")
    return float(value)


def _enum(value: object, enum_type: type[CameraBackend], path: str) -> CameraBackend:
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"unsupported {path}: {value!r}") from error
