"""Typed values loaded from DivergenceSplitter JSON files.

Two independent documents share these types:

* :class:`AppSettings` is the application-wide settings the application itself
  persists (log level, reaction time, and the last used Profile path).
* :class:`Profile` is the per-game/category/environment document holding the
  frame source and the LiveSplit-bound instances.

Both have their own schema version and never embed each other's fields.
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from divergencesplitter.frame.normalizer import (
    CropMargins,
    OutputSize,
    ResizeInterpolation,
)
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
    left: int
    right: int
    top: int
    bottom: int

    def __post_init__(self) -> None:
        if min(self.left, self.right, self.top, self.bottom) < 0:
            raise ValueError("crop margins must be non-negative")

    def to_crop_margins(self) -> CropMargins:
        return CropMargins(self.left, self.right, self.top, self.bottom)


@dataclass(frozen=True)
class ResizeConfiguration:
    width: int
    height: int
    interpolation: ResizeInterpolation = ResizeInterpolation.AREA
    resize_references: bool = False

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


@dataclass(frozen=True)
class NdiSourceConfiguration:
    """One NDI source addressed by its advertised name, never by list index."""

    name: str
    transform: SourceTransformConfiguration = SourceTransformConfiguration()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("NDI source name must not be empty")


type SourceConfiguration = (
    CameraSourceConfiguration | VideoSourceConfiguration | NdiSourceConfiguration
)


@dataclass(frozen=True)
class InstanceConfiguration:
    connection: LiveSplitConnection
    scenario: str

    def __post_init__(self) -> None:
        if not self.scenario:
            raise ValueError("scenario path must not be empty")


APP_SETTINGS_VERSION = 1
PROFILE_VERSION = 1

_LOG_LEVELS = frozenset({"OFF", "DEBUG", "INFO", "WARNING", "ERROR"})


class Theme(StrEnum):
    """The appearance theme selected in App Settings."""

    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class UiSettings:
    """Application appearance settings, independent of any Profile."""

    theme: Theme = Theme.LIGHT

    def __post_init__(self) -> None:
        if not isinstance(self.theme, Theme):
            raise TypeError(f"unsupported theme: {self.theme!r}")


def _is_absolute_path(value: str) -> bool:
    try:
        return Path(value).is_absolute()
    except OSError, ValueError:
        return False


@dataclass(frozen=True)
class AppSettings:
    """Application-wide settings persisted by the application itself.

    These values are independent of any Profile: changing the selected Profile
    never rewrites them, and they stay valid across Profile changes.
    """

    version: int
    log_level: str
    reaction_time_ms: int = 0
    last_profile: str | None = None
    ui: UiSettings = field(default_factory=UiSettings)

    def __post_init__(self) -> None:
        if self.version != APP_SETTINGS_VERSION:
            raise ValueError(f"unsupported app settings version: {self.version!r}")
        if self.log_level not in _LOG_LEVELS:
            raise ValueError(f"unsupported log level: {self.log_level!r}")
        if type(self.reaction_time_ms) is not int or self.reaction_time_ms < 0:
            raise ValueError("reaction_time_ms must be a non-negative integer")
        if self.last_profile is not None:
            if type(self.last_profile) is not str:
                raise TypeError("last_profile must be a string or null")
            if not _is_absolute_path(self.last_profile):
                raise ValueError("last_profile must be an absolute path")


@dataclass(frozen=True)
class Profile:
    """One game/category/environment profile, independent of App Settings.

    Every file path a Profile owns is absolute; a Profile is never resolved
    against the directory that contains the Profile document. Only paths inside
    a Scenario YAML keep their own relative-reference semantics.
    """

    version: int
    source: SourceConfiguration
    instances: tuple[InstanceConfiguration, ...]

    def __post_init__(self) -> None:
        if self.version != PROFILE_VERSION:
            raise ValueError(f"unsupported profile version: {self.version!r}")
        if isinstance(self.source, VideoSourceConfiguration) and not _is_absolute_path(
            self.source.path
        ):
            raise ValueError("video source path must be an absolute path")
        for instance in self.instances:
            if not _is_absolute_path(instance.scenario):
                raise ValueError("scenario path must be an absolute path")
