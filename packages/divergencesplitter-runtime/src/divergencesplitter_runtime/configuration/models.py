"""Typed values loaded from a DivergenceSplitter JSON configuration file."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraDeviceConfiguration:
    name: str
    id: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("camera device name must not be empty")
        if self.id < 0:
            raise ValueError("camera device id must be non-negative")


@dataclass(frozen=True)
class CameraSourceConfiguration:
    device: CameraDeviceConfiguration
    width: int
    height: int
    fps: float

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("camera width must be positive")
        if self.height <= 0:
            raise ValueError("camera height must be positive")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("camera fps must be finite and positive")


@dataclass(frozen=True)
class VideoSourceConfiguration:
    path: str

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("video path must not be empty")


type SourceConfiguration = CameraSourceConfiguration | VideoSourceConfiguration


@dataclass(frozen=True)
class ScenarioConfiguration:
    script: str

    def __post_init__(self) -> None:
        if not self.script:
            raise ValueError("scenario script must not be empty")


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
    scenario: ScenarioConfiguration
    runtime: RuntimeConfiguration

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError(f"unsupported configuration version: {self.version!r}")
