"""Build frame sources from parsed configuration values."""

import importlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, assert_never, cast

from divergencesplitter.frame.camera import OpenCvCameraSource
from divergencesplitter.frame.source import FrameSource
from divergencesplitter.frame.video_file import VideoFileSource

from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    SourceConfiguration,
    VideoSourceConfiguration,
)


class SourceConfigurationError(Exception):
    """A configured frame source cannot be resolved or constructed."""


class CaptureModeInfo(Protocol):
    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    @property
    def fps(self) -> float: ...

    @property
    def format(self) -> str | None: ...

    @property
    def subtype_guid(self) -> str: ...


class CameraDeviceInfo(Protocol):
    """A camera device as reported by the platform-specific enumerator."""

    @property
    def name(self) -> str: ...

    @property
    def index(self) -> int: ...

    @property
    def backend(self) -> object: ...

    @property
    def modes(self) -> Sequence[CaptureModeInfo]: ...


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
        device = resolve_camera_device(configuration.device, devices)
        mode = resolve_camera_mode(configuration.mode, device.modes, device=device)
        module = importlib.import_module("windows_capture_device_list")
        return OpenCvCameraSource(
            capture_factory=lambda: module.open_video_capture(cast(Any, mode)),
            request_60_fps=configuration.request_60_fps,
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
) -> CameraDeviceInfo:
    """Resolve backend/name and use index only to disambiguate duplicate names."""

    matches = [
        device
        for device in devices
        if _backend_value(device.backend) == configured.backend.value
        and device.name == configured.name
    ]
    if not matches:
        raise SourceConfigurationError(
            "camera device is not connected: "
            f"backend={configured.backend.value!r}, name={configured.name!r}, "
            f"index={configured.index!r}"
        )
    if len(matches) == 1:
        return matches[0]
    for device in matches:
        if device.index == configured.index:
            return device
    raise SourceConfigurationError(
        "multiple camera devices have the configured name and none has "
        f"the configured index: name={configured.name!r}, index={configured.index!r}"
    )


def resolve_camera_mode(
    configured: CameraModeConfiguration,
    modes: Sequence[CaptureModeInfo],
    *,
    device: CameraDeviceInfo | None = None,
) -> CaptureModeInfo:
    """Resolve only the exact enumerated mode, allowing tiny FPS roundoff."""

    for mode in modes:
        if (
            mode.width == configured.width
            and mode.height == configured.height
            and mode.subtype_guid == configured.subtype_guid
            and math.isclose(
                mode.fps,
                configured.fps,
                rel_tol=1e-6,
                abs_tol=1e-6,
            )
        ):
            return mode
    device_context = ""
    if device is not None:
        device_context = (
            f"backend={_backend_value(device.backend)!r}, device={device.name!r}, "
        )
    raise SourceConfigurationError(
        "configured camera mode is unavailable: "
        f"{device_context}"
        f"{configured.width}x{configured.height}@{configured.fps} "
        f"{configured.subtype_guid!r}"
    )


def _backend_value(backend: object) -> str:
    value = getattr(backend, "value", None)
    if isinstance(value, str):
        return value
    name = getattr(backend, "name", "")
    return str(name).lower()


def resolve_configuration_path(path: str, *, base_directory: Path) -> Path:
    """Resolve a configuration-owned path against its file directory."""

    return _resolve_path(path, base_directory)


def _resolve_path(path: str, base_directory: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return base_directory / candidate
