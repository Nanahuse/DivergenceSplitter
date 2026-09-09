"""Typed values loaded from a DivergenceSplitter JSON configuration file."""

import math
from dataclasses import dataclass
from enum import StrEnum

from divergencesplitter.frame.normalizer import ClipRegion, OutputSize
from divergencesplitter.livesplit.models import LiveSplitConnection


class CameraBackend(StrEnum):
    DIRECT_SHOW = "direct_show"
    MEDIA_FOUNDATION = "media_foundation"


@dataclass(frozen=True)
class CameraDeviceConfiguration:
    backend: CameraBackend
    name: str
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.backend, CameraBackend):
            raise TypeError(f"unsupported camera backend: {self.backend!r}")
        if not self.name:
            raise ValueError("camera device name must not be empty")
        if type(self.index) is not int or self.index < 0:
            raise ValueError("camera device index must be non-negative")


@dataclass(frozen=True)
class CameraModeConfiguration:
    width: int
    height: int
    fps: float
    subtype_guid: str

    def __post_init__(self) -> None:
        if type(self.width) is not int or self.width <= 0:
            raise ValueError("camera width must be positive")
        if type(self.height) is not int or self.height <= 0:
            raise ValueError("camera height must be positive")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("camera fps must be finite and positive")
        if not self.subtype_guid:
            raise ValueError("camera subtype GUID must not be empty")


@dataclass(frozen=True)
class CropConfiguration:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("crop coordinates must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("crop dimensions must be positive")

    def to_clip_region(self) -> ClipRegion:
        return ClipRegion(self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class ResizeConfiguration:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("resize dimensions must be positive")

    def to_output_size(self) -> OutputSize:
        return OutputSize(self.width, self.height)


@dataclass(frozen=True)
class SourceTransformConfiguration:
    crop: CropConfiguration | None = None
    resize: ResizeConfiguration | None = None


@dataclass(frozen=True)
class CameraSourceConfiguration:
    device: CameraDeviceConfiguration
    mode: CameraModeConfiguration
    request_60_fps: bool
    transform: SourceTransformConfiguration = SourceTransformConfiguration()

    def __post_init__(self) -> None:
        if type(self.request_60_fps) is not bool:
            raise TypeError("camera request_60_fps must be a boolean")


@dataclass(frozen=True)
class VideoSourceConfiguration:
    path: str
    transform: SourceTransformConfiguration = SourceTransformConfiguration()

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("video path must not be empty")


type SourceConfiguration = CameraSourceConfiguration | VideoSourceConfiguration


@dataclass(frozen=True)
class InstanceConfiguration:
    connection: LiveSplitConnection
    scenario: str

    def __post_init__(self) -> None:
        if not self.scenario:
            raise ValueError("scenario path must not be empty")


@dataclass(frozen=True)
class RuntimeConfiguration:
    log_level: str

    def __post_init__(self) -> None:
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(f"unsupported log level: {self.log_level!r}")


@dataclass(frozen=True)
class ApplicationConfiguration:
    version: int
    source: SourceConfiguration
    instances: tuple[InstanceConfiguration, ...]
    runtime: RuntimeConfiguration

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError(f"unsupported configuration version: {self.version!r}")
