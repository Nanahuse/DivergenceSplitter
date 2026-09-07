import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from divergencesplitter.frame.camera import OpenCvCameraSource
from divergencesplitter.frame.video_file import VideoFileSource
from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_configuration,
    save_configuration,
)
from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraSourceConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    CameraDeviceInfo,
    SourceConfigurationError,
    build_frame_source,
    resolve_camera_device,
    resolve_configuration_path,
)


def camera_configuration() -> dict[str, object]:
    return {
        "version": 1,
        "source": {
            "type": "camera",
            "device": {"name": "USB Camera", "id": 2},
            "width": 1280,
            "height": 720,
            "fps": 60,
        },
        "instances": [
            {
                "connection": {
                    "rpc_endpoint": "tcp://127.0.0.1:54000",
                    "event_endpoint": "tcp://127.0.0.1:54001",
                },
                "scenario": "./scenario.py",
            }
        ],
        "runtime": {"log_level": "INFO"},
    }


def write_configuration(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_loads_camera_configuration(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write_configuration(path, camera_configuration())

    configuration = load_configuration(path)

    assert configuration.version == 1
    assert configuration.source == CameraSourceConfiguration(
        CameraDeviceConfiguration("USB Camera", 2),
        1280,
        720,
        60.0,
    )
    assert len(configuration.instances) == 1
    assert configuration.instances[0].scenario == "./scenario.py"
    assert configuration.instances[0].connection.rpc_endpoint == "tcp://127.0.0.1:54000"
    assert (
        configuration.instances[0].connection.event_endpoint == "tcp://127.0.0.1:54001"
    )
    assert configuration.runtime.log_level == "INFO"


def test_loads_multiple_instances(tmp_path: Path) -> None:
    value = camera_configuration()
    value["instances"] = [
        {
            "connection": {
                "rpc_endpoint": "tcp://127.0.0.1:54000",
                "event_endpoint": "tcp://127.0.0.1:54001",
            },
            "scenario": "./main.yaml",
        },
        {
            "connection": {
                "rpc_endpoint": "tcp://127.0.0.1:54100",
                "event_endpoint": "tcp://127.0.0.1:54101",
            },
            "scenario": "./sub.py",
        },
    ]
    path = tmp_path / "config.json"
    write_configuration(path, value)

    configuration = load_configuration(path)

    assert [instance.scenario for instance in configuration.instances] == [
        "./main.yaml",
        "./sub.py",
    ]
    assert configuration.instances[1].connection.rpc_endpoint == "tcp://127.0.0.1:54100"


def test_loads_video_configuration(tmp_path: Path) -> None:
    value = camera_configuration()
    value["source"] = {"type": "video", "path": "./run.mp4"}
    path = tmp_path / "config.json"
    write_configuration(path, value)

    configuration = load_configuration(path)

    assert configuration.source == VideoSourceConfiguration("./run.mp4")


@pytest.mark.parametrize(
    "content",
    [
        '{"version": 1,}',
        '{"version": NaN}',
        '{"version": Infinity}',
        '{"version": 1, "version": 1}',
        '{/* comment */ "version": 1}',
    ],
)
def test_rejects_non_standard_or_ambiguous_json(
    tmp_path: Path,
    content: str,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationFileError):
        load_configuration(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing runtime",
        "unknown root",
        "unknown version",
        "unknown source",
        "unknown camera field",
        "boolean width",
        "missing instances",
        "unknown instance field",
        "unknown connection field",
    ],
)
def test_rejects_invalid_schema(tmp_path: Path, mutation: str) -> None:
    value = camera_configuration()
    source = cast(dict[str, object], value["source"])
    if mutation == "missing runtime":
        value.pop("runtime")
    elif mutation == "unknown root":
        value["unknown"] = 1
    elif mutation == "unknown version":
        value["version"] = 2
    elif mutation == "unknown source":
        value["source"] = {"type": "ndi"}
    elif mutation == "unknown camera field":
        source["path"] = "unexpected.mp4"
    elif mutation == "boolean width":
        source["width"] = True
    elif mutation == "missing instances":
        value.pop("instances")
    elif mutation == "unknown instance field":
        instance = cast(list[dict[str, object]], value["instances"])[0]
        instance["unknown"] = 1
    elif mutation == "unknown connection field":
        instance = cast(list[dict[str, object]], value["instances"])[0]
        connection = cast(dict[str, object], instance["connection"])
        connection["unknown"] = 1
    path = tmp_path / "config.json"
    write_configuration(path, value)

    with pytest.raises(ConfigurationValidationError):
        load_configuration(path)


def test_resolves_unique_name_even_when_saved_id_changed() -> None:
    configured = CameraDeviceConfiguration("USB Camera", 2)
    devices = cast(
        list[CameraDeviceInfo],
        [SimpleNamespace(name="USB Camera", id=7)],
    )

    assert resolve_camera_device(configured, devices) == 7


def test_resolves_duplicate_name_with_saved_id() -> None:
    configured = CameraDeviceConfiguration("USB Camera", 2)
    devices = cast(
        list[CameraDeviceInfo],
        [
            SimpleNamespace(name="USB Camera", id=1),
            SimpleNamespace(name="USB Camera", id=2),
        ],
    )

    assert resolve_camera_device(configured, devices) == 2


@pytest.mark.parametrize(
    "devices",
    [
        [],
        [
            SimpleNamespace(name="USB Camera", id=1),
            SimpleNamespace(name="USB Camera", id=3),
        ],
    ],
)
def test_camera_resolution_failure_requires_reselection(devices: list[object]) -> None:
    configured = CameraDeviceConfiguration("USB Camera", 2)

    with pytest.raises(SourceConfigurationError):
        resolve_camera_device(configured, cast(list[CameraDeviceInfo], devices))


def test_builds_camera_source_from_current_device_id(tmp_path: Path) -> None:
    configuration = CameraSourceConfiguration(
        CameraDeviceConfiguration("USB Camera", 2),
        1280,
        720,
        60.0,
    )
    devices = [SimpleNamespace(name="USB Camera", id=7)]

    with patch(
        "divergencesplitter_runtime.configuration.source_builder._list_camera_devices",
        return_value=devices,
    ):
        source = build_frame_source(configuration, base_directory=tmp_path)

    assert isinstance(source, OpenCvCameraSource)
    assert source.device_index == 7
    assert source.width == 1280
    assert source.height == 720
    assert source.fps == 60.0


def test_camera_enumeration_failure_is_reported(tmp_path: Path) -> None:
    configuration = CameraSourceConfiguration(
        CameraDeviceConfiguration("USB Camera", 2),
        1280,
        720,
        60.0,
    )

    with (
        patch(
            "divergencesplitter_runtime.configuration.source_builder._list_camera_devices",
            side_effect=RuntimeError("enumeration failed"),
        ),
        pytest.raises(
            SourceConfigurationError,
            match="failed to enumerate camera devices",
        ),
    ):
        build_frame_source(configuration, base_directory=tmp_path)


def test_builds_video_source_relative_to_configuration(tmp_path: Path) -> None:
    source = build_frame_source(
        VideoSourceConfiguration("media/run.mp4"),
        base_directory=tmp_path,
    )

    assert isinstance(source, VideoFileSource)
    assert Path(source.path) == tmp_path / "media" / "run.mp4"


def test_resolves_scenario_path_relative_to_configuration(tmp_path: Path) -> None:
    assert (
        resolve_configuration_path(
            "scenarios/run.py",
            base_directory=tmp_path,
        )
        == tmp_path / "scenarios" / "run.py"
    )


def test_save_then_load_round_trips_camera_configuration(tmp_path: Path) -> None:
    original = load_configuration(
        _write_configuration(tmp_path, camera_configuration())
    )

    path = tmp_path / "saved.json"
    save_configuration(path, original)

    assert load_configuration(path) == original


def test_save_preserves_readable_non_ascii_values(tmp_path: Path) -> None:
    value = camera_configuration()
    source = cast(dict[str, object], value["source"])
    device = cast(dict[str, object], source["device"])
    device["name"] = "日本語カメラ"
    original = load_configuration(_write_configuration(tmp_path, value))

    path = tmp_path / "saved.json"
    save_configuration(path, original)

    assert "日本語カメラ" in path.read_text(encoding="utf-8")


def test_save_then_load_round_trips_video_configuration(tmp_path: Path) -> None:
    value = camera_configuration()
    value["source"] = {"type": "video", "path": "./run.mp4"}
    original = load_configuration(_write_configuration(tmp_path, value))

    path = tmp_path / "saved.json"
    save_configuration(path, original)

    assert load_configuration(path) == original


def _write_configuration(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "config.json"
    write_configuration(path, value)
    return path
