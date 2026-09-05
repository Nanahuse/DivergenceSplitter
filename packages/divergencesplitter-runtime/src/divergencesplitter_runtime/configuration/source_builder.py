"""Build frame sources from parsed configuration values."""

import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, assert_never

from divergencesplitter.frame.camera import OpenCvCameraSource
from divergencesplitter.frame.source import FrameSource
from divergencesplitter.frame.video_file import VideoFileSource

from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraSourceConfiguration,
    SourceConfiguration,
    VideoSourceConfiguration,
)


class SourceConfigurationError(Exception):
    """A configured frame source cannot be resolved or constructed."""


class CameraDeviceInfo(Protocol):
    """A camera device as reported by the platform-specific enumerator."""

    @property
    def name(self) -> str: ...

    @property
    def id(self) -> int: ...


def build_frame_source(
    configuration: SourceConfiguration,
    *,
    base_directory: Path,
) -> FrameSource:
    """Build the concrete source selected by a parsed configuration."""

    if isinstance(configuration, CameraSourceConfiguration):
        try:
            devices = _list_camera_devices()
        except Exception as error:
            raise SourceConfigurationError(
                "failed to enumerate camera devices"
            ) from error
        device_id = resolve_camera_device(configuration.device, devices)
        return OpenCvCameraSource(
            device_index=device_id,
            width=configuration.width,
            height=configuration.height,
            fps=configuration.fps,
        )
    if isinstance(configuration, VideoSourceConfiguration):
        path = _resolve_path(configuration.path, base_directory)
        return VideoFileSource(str(path))
    assert_never(configuration)


def _list_camera_devices() -> Sequence[CameraDeviceInfo]:
    """Enumerate camera devices through the Windows-only boundary package."""

    module = importlib.import_module("windows_capture_device_list")
    return module.list_devices()


def resolve_camera_device(
    configured: CameraDeviceConfiguration,
    devices: Sequence[CameraDeviceInfo],
) -> int:
    """Resolve a saved name and disambiguating id to the current device id."""

    matches = [device for device in devices if device.name == configured.name]
    if not matches:
        raise SourceConfigurationError(
            f"camera device is not connected: {configured.name!r}"
        )
    if len(matches) == 1:
        return matches[0].id
    for device in matches:
        if device.id == configured.id:
            return device.id
    raise SourceConfigurationError(
        "multiple camera devices have the configured name and none has "
        f"the configured id: name={configured.name!r}, id={configured.id!r}"
    )


def resolve_configuration_path(path: str, *, base_directory: Path) -> Path:
    """Resolve a configuration-owned path against its file directory."""

    return _resolve_path(path, base_directory)


def _resolve_path(path: str, base_directory: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return base_directory / candidate
