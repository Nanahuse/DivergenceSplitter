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
)
from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraSourceConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    build_frame_source,
    resolve_camera_device,
    resolve_configuration_path,
)
from windows_capture_device_list import CaptureDevice


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
        "scenario": {"script": "./scenario.py"},
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
    assert configuration.scenario.script == "./scenario.py"
    assert configuration.runtime.log_level == "INFO"


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
    path = tmp_path / "config.json"
    write_configuration(path, value)

    with pytest.raises(ConfigurationValidationError):
        load_configuration(path)


def test_resolves_unique_name_even_when_saved_id_changed() -> None:
    configured = CameraDeviceConfiguration("USB Camera", 2)
    devices = cast(
        list[CaptureDevice],
        [SimpleNamespace(name="USB Camera", id=7)],
    )

    assert resolve_camera_device(configured, devices) == 7


def test_resolves_duplicate_name_with_saved_id() -> None:
    configured = CameraDeviceConfiguration("USB Camera", 2)
    devices = cast(
        list[CaptureDevice],
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
        resolve_camera_device(configured, cast(list[CaptureDevice], devices))


def test_builds_camera_source_from_current_device_id(tmp_path: Path) -> None:
    configuration = CameraSourceConfiguration(
        CameraDeviceConfiguration("USB Camera", 2),
        1280,
        720,
        60.0,
    )
    devices = [SimpleNamespace(name="USB Camera", id=7)]

    with patch(
        "divergencesplitter_runtime.configuration.source_builder.list_devices",
        return_value=devices,
    ):
        source = build_frame_source(configuration, base_directory=tmp_path)

    assert isinstance(source, OpenCvCameraSource)
    assert source.device_index == 7
    assert source.width == 1280
    assert source.height == 720
    assert source.fps == 60.0


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
