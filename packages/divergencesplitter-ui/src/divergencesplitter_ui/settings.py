"""Pure settings draft and confirmation decisions for the settings screen.

Nothing in this module imports Dear PyGui. It owns the *what* of editing one
configuration: parsing a loaded configuration into an editable draft, applying
user edits without mutating the draft, deciding which fields are editable while
a session is active, and deciding whether a confirmation saves, starts, or
reflects a log-level change. The Dear PyGui widgets only call into these
helpers.

The single authority for the persisted values remains the JSON file; the draft
here is an in-memory projection shared by the main screen and the settings
screen so they never fork the value.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraDeviceConfiguration,
    CameraSourceConfiguration,
    RuntimeConfiguration,
    ScenarioConfiguration,
    SourceConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_device,
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class CameraDevice(Protocol):
    """A camera device as reported by the platform-specific enumerator."""

    @property
    def name(self) -> str: ...

    @property
    def id(self) -> int: ...


class CameraEnumerator(Protocol):
    """Enumerate connected camera devices as name/id pairs."""

    def list_devices(self) -> Sequence[CameraDevice]: ...


class WindowsCameraEnumerator:
    """Enumerate cameras through the Windows-only boundary package."""

    def list_devices(self) -> Sequence[CameraDevice]:
        module = importlib.import_module("windows_capture_device_list")
        return module.list_devices()


def select_configured_camera(
    configured: CameraDeviceConfiguration,
    devices: Sequence[CameraDevice],
) -> CameraDevice | None:
    """Select a current device with the shared name/id resolution rules."""

    try:
        selected_id = resolve_camera_device(configured, devices)
    except SourceConfigurationError:
        return None
    return next(
        device
        for device in devices
        if device.name == configured.name and device.id == selected_id
    )


@dataclass(frozen=True)
class SettingsDraft:
    """Transfer values for one editable configuration projection."""

    configuration_path: Path
    scenario_script: str
    source: SourceConfiguration
    log_level: str


def camera_source(draft: SettingsDraft) -> CameraSourceConfiguration | None:
    """Return the camera source carried by a draft, if any."""

    if isinstance(draft.source, CameraSourceConfiguration):
        return draft.source
    return None


def draft_from_configuration(
    configuration: ApplicationConfiguration,
    path: Path,
) -> SettingsDraft:
    """Project one loaded configuration into the shared editable draft."""

    return SettingsDraft(
        configuration_path=path,
        scenario_script=configuration.scenario.script,
        source=configuration.source,
        log_level=configuration.runtime.log_level,
    )


def configuration_from_draft(draft: SettingsDraft) -> ApplicationConfiguration:
    """Build a validated configuration from current draft values."""

    return ApplicationConfiguration(
        version=1,
        source=draft.source,
        scenario=ScenarioConfiguration(draft.scenario_script),
        runtime=RuntimeConfiguration(draft.log_level),
    )


@dataclass(frozen=True)
class EditPermission:
    """Which draft fields may be edited for a given session phase."""

    source: bool
    scenario: bool
    log_level: bool


def edit_permission(*, active: bool) -> EditPermission:
    """Resolve editability from whether a session is currently in progress.

    Source and scenario are disabled while active so an in-flight session never
    changes its input or scenario. Log level stays editable and is reflected to
    the active diagnostics on confirmation.
    """

    return EditPermission(
        source=not active,
        scenario=not active,
        log_level=True,
    )


@dataclass(frozen=True)
class SaveDecision:
    """What saving should do after persisting the current draft."""

    start: bool
    reflect_log_level: bool


def save_decision(*, active: bool) -> SaveDecision:
    """Decide the session effect of saving a configuration.

    Saving starts a session when none is active. During an active session it
    only reflects the editable log level to the current diagnostics.
    """

    if active:
        return SaveDecision(start=False, reflect_log_level=True)
    return SaveDecision(start=True, reflect_log_level=False)


@dataclass(frozen=True)
class CameraDimensions:
    """Parsed camera-specific numeric values from the settings screen."""

    width: int
    height: int
    fps: float


def parse_camera_dimensions(
    width: str,
    height: str,
    fps: str,
) -> CameraDimensions:
    """Parse camera widget text into typed values, rejecting invalid input."""

    width_value = int(width)
    height_value = int(height)
    fps_value = float(fps)
    return CameraDimensions(width_value, height_value, fps_value)


class SettingsModel:
    """Own the single editable draft shared by the main and settings screens.

    The persisted JSON stays the authority for saved values; this model is the
    in-memory projection both screens edit so a value is never forked. All edit
    operations return the updated draft and leave it untouched when no
    configuration is open or the source type is not editable.
    """

    def __init__(self, camera_enumerator: CameraEnumerator) -> None:
        self._camera_enumerator = camera_enumerator
        self._draft: SettingsDraft | None = None

    @property
    def draft(self) -> SettingsDraft | None:
        return self._draft

    def open_configuration(
        self,
        configuration: ApplicationConfiguration,
        path: Path,
    ) -> SettingsDraft:
        draft = draft_from_configuration(configuration, path)
        self._draft = draft
        return draft

    def list_cameras(self) -> Sequence[CameraDevice]:
        return self._camera_enumerator.list_devices()

    def set_scenario_script(self, script: str) -> SettingsDraft | None:
        if self._draft is None:
            return None
        self._draft = replace(self._draft, scenario_script=script)
        return self._draft

    def set_log_level(self, level: str) -> SettingsDraft | None:
        if self._draft is None:
            return None
        self._draft = replace(self._draft, log_level=level)
        return self._draft

    def set_camera_device(self, name: str, id: int) -> SettingsDraft | None:
        if self._draft is None:
            return None
        camera = camera_source(self._draft)
        if camera is None:
            return self._draft
        self._draft = replace(
            self._draft,
            source=CameraSourceConfiguration(
                CameraDeviceConfiguration(name, id),
                camera.width,
                camera.height,
                camera.fps,
            ),
        )
        return self._draft

    def set_camera_dimensions(
        self,
        width: int,
        height: int,
        fps: float,
    ) -> SettingsDraft | None:
        if self._draft is None:
            return None
        camera = camera_source(self._draft)
        if camera is None:
            return self._draft
        self._draft = replace(
            self._draft,
            source=CameraSourceConfiguration(
                camera.device,
                width,
                height,
                fps,
            ),
        )
        return self._draft

    def configuration(self) -> ApplicationConfiguration | None:
        if self._draft is None:
            return None
        return configuration_from_draft(self._draft)
