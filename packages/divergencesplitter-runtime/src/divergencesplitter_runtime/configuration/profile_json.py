"""Strict Profile JSON loading and saving.

A Profile document holds the frame source and the LiveSplit-bound instances
only. It has its own schema version and never embeds runtime/app settings: an
unknown ``runtime`` field is rejected like any other unknown field. Every file
path inside a Profile is absolute; relative paths are rejected here and are only
allowed inside a Scenario document, resolved by the Scenario loader.
"""

from __future__ import annotations

from pathlib import Path
from typing import assert_never

from divergencesplitter.livesplit.models import LiveSplitConnection

from divergencesplitter_runtime.configuration.models import (
    PROFILE_VERSION,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    CropConfiguration,
    InstanceConfiguration,
    NdiSourceConfiguration,
    Profile,
    ResizeConfiguration,
    ResizeInterpolation,
    SourceConfiguration,
    SourceTransformConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.strict_json import (
    ConfigurationValidationError,
    array_value,
    boolean_value,
    check_keys,
    dump_json_document,
    enum_value,
    integer_value,
    load_json_document,
    number_value,
    object_value,
    string_value,
)


def load_profile(path: str | Path) -> Profile:
    """Load one versioned Profile file."""

    value = load_json_document(path)
    try:
        root = object_value(value, "profile")
        check_keys(root, required={"version", "source", "instances"})
        version = integer_value(root["version"], "version")
        if version != PROFILE_VERSION:
            raise ValueError(f"unsupported profile version: {version!r}")
        source = _source(root["source"])
        instances = _instances(root["instances"])
        return Profile(version, source, instances)
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationValidationError(str(error)) from error


def save_profile(path: str | Path, profile: Profile) -> None:
    """Write one Profile as canonical JSON that round-trips through ``load_profile``."""

    Path(path).write_text(_dump(profile), encoding="utf-8")


def _dump(profile: Profile) -> str:
    return dump_json_document(
        {
            "version": profile.version,
            "source": _source_dict(profile.source),
            "instances": [_instance_dict(instance) for instance in profile.instances],
        }
    )


def _instance_dict(instance: InstanceConfiguration) -> dict[str, object]:
    return {
        "connection": {
            "rpc_endpoint": instance.connection.rpc_endpoint,
            "event_endpoint": instance.connection.event_endpoint,
        },
        "scenario": instance.scenario,
    }


def _source_dict(source: SourceConfiguration) -> dict[str, object]:
    match source:
        case CameraSourceConfiguration():
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
        case VideoSourceConfiguration():
            return {
                "type": "video",
                "path": source.path,
                "transform": _transform_dict(source.transform),
            }
        case NdiSourceConfiguration():
            return {
                "type": "ndi",
                "name": source.name,
                "transform": _transform_dict(source.transform),
            }
    assert_never(source)


def _source(value: object) -> SourceConfiguration:
    source = object_value(value, "source")
    source_type = string_value(source.get("type"), "source.type")
    match source_type:
        case "camera":
            check_keys(
                source,
                required={"type", "device", "mode", "request_60_fps"},
                optional={"transform"},
            )
            device_value = object_value(source["device"], "source.device")
            check_keys(device_value, required={"backend", "name", "index"})
            device = CameraDeviceConfiguration(
                enum_value(
                    device_value["backend"], CameraBackend, "source.device.backend"
                ),
                string_value(device_value["name"], "source.device.name"),
                integer_value(device_value["index"], "source.device.index"),
            )
            mode_value = object_value(source["mode"], "source.mode")
            check_keys(mode_value, required={"width", "height", "fps", "subtype_guid"})
            mode = CameraModeConfiguration(
                integer_value(mode_value["width"], "source.mode.width"),
                integer_value(mode_value["height"], "source.mode.height"),
                number_value(mode_value["fps"], "source.mode.fps"),
                string_value(mode_value["subtype_guid"], "source.mode.subtype_guid"),
            )
            return CameraSourceConfiguration(
                device,
                mode,
                boolean_value(source["request_60_fps"], "source.request_60_fps"),
                _transform(source["transform"], "source.transform")
                if "transform" in source
                else SourceTransformConfiguration(),
            )
        case "video":
            check_keys(source, required={"type", "path"}, optional={"transform"})
            return VideoSourceConfiguration(
                string_value(source["path"], "source.path"),
                _transform(source["transform"], "source.transform")
                if "transform" in source
                else SourceTransformConfiguration(),
            )
        case "ndi":
            check_keys(source, required={"type", "name"}, optional={"transform"})
            return NdiSourceConfiguration(
                string_value(source["name"], "source.name"),
                _transform(source["transform"], "source.transform")
                if "transform" in source
                else SourceTransformConfiguration(),
            )
    raise ValueError(f"unsupported source type: {source_type!r}")


def _instances(value: object) -> tuple[InstanceConfiguration, ...]:
    instances = array_value(value, "instances")
    return tuple(_instance(item, index) for index, item in enumerate(instances))


def _instance(value: object, index: int) -> InstanceConfiguration:
    prefix = f"instances[{index}]"
    instance = object_value(value, prefix)
    check_keys(instance, required={"connection", "scenario"})
    connection = _connection(instance["connection"], f"{prefix}.connection")
    scenario = string_value(instance["scenario"], f"{prefix}.scenario")
    return InstanceConfiguration(connection, scenario)


def _connection(value: object, path: str) -> LiveSplitConnection:
    connection = object_value(value, path)
    check_keys(connection, required={"rpc_endpoint", "event_endpoint"})
    return LiveSplitConnection(
        string_value(connection["rpc_endpoint"], f"{path}.rpc_endpoint"),
        string_value(connection["event_endpoint"], f"{path}.event_endpoint"),
    )


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
        else {
            "width": transform.resize.width,
            "height": transform.resize.height,
            "interpolation": transform.resize.interpolation.value,
            "resize_references": transform.resize.resize_references,
        },
    }


def _transform(value: object, path: str) -> SourceTransformConfiguration:
    transform = object_value(value, path)
    check_keys(transform, required={"crop", "resize"})
    crop_value = transform["crop"]
    crop = None
    if crop_value is not None:
        crop_object = object_value(crop_value, f"{path}.crop")
        check_keys(crop_object, required={"left", "right", "top", "bottom"})
        crop = CropConfiguration(
            integer_value(crop_object["left"], f"{path}.crop.left"),
            integer_value(crop_object["right"], f"{path}.crop.right"),
            integer_value(crop_object["top"], f"{path}.crop.top"),
            integer_value(crop_object["bottom"], f"{path}.crop.bottom"),
        )
    resize_value = transform["resize"]
    resize = None
    if resize_value is not None:
        resize_object = object_value(resize_value, f"{path}.resize")
        check_keys(
            resize_object,
            required={"width", "height"},
            optional={"interpolation", "resize_references"},
        )
        resize = ResizeConfiguration(
            integer_value(resize_object["width"], f"{path}.resize.width"),
            integer_value(resize_object["height"], f"{path}.resize.height"),
            ResizeInterpolation(resize_object.get("interpolation", "area")),
            bool(resize_object.get("resize_references", False)),
        )
    return SourceTransformConfiguration(crop, resize)
