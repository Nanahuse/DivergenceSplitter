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

from divergencesplitter.livesplit.models import LiveSplitConnection
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    RuntimeConfiguration,
    SourceConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_device,
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class CameraMode(Protocol):
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


class CameraDevice(Protocol):
    """A camera device as reported by the platform-specific enumerator."""

    @property
    def name(self) -> str: ...

    @property
    def backend(self) -> object: ...

    @property
    def index(self) -> int: ...

    @property
    def modes(self) -> Sequence[CameraMode]: ...


class CameraEnumerator(Protocol):
    """Enumerate connected camera devices and their modes."""

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
        selected = resolve_camera_device(configured, devices)
    except SourceConfigurationError:
        return None
    return next(device for device in devices if device is selected)


@dataclass(frozen=True)
class CameraSourceDraft:
    device: CameraDeviceConfiguration
    mode: CameraModeConfiguration | None


@dataclass(frozen=True)
class InstanceDraft:
    """Editable transfer values for one instance of a settings projection.

    Unlike the persisted ``InstanceConfiguration``, the empty strings that a
    newly added instance starts with are valid here; they are only rejected when
    the whole draft is saved.
    """

    rpc_endpoint: str
    event_endpoint: str
    scenario: str


@dataclass(frozen=True)
class SettingsDraft:
    """Transfer values for one editable configuration projection."""

    configuration_path: Path
    instances: tuple[InstanceDraft, ...]
    source: SourceConfiguration | CameraSourceDraft
    log_level: str


def camera_source(draft: SettingsDraft) -> CameraSourceDraft | None:
    """Return the camera source carried by a draft, if any."""

    if isinstance(draft.source, (CameraSourceConfiguration, CameraSourceDraft)):
        if isinstance(draft.source, CameraSourceConfiguration):
            return CameraSourceDraft(draft.source.device, draft.source.mode)
        return draft.source
    return None


def draft_from_configuration(
    configuration: ApplicationConfiguration,
    path: Path,
) -> SettingsDraft:
    """Project one loaded configuration into the shared editable draft."""

    instances = tuple(
        InstanceDraft(
            rpc_endpoint=instance.connection.rpc_endpoint,
            event_endpoint=instance.connection.event_endpoint,
            scenario=instance.scenario,
        )
        for instance in configuration.instances
    )
    return SettingsDraft(
        configuration_path=path,
        instances=instances,
        source=configuration.source,
        log_level=configuration.runtime.log_level,
    )


def validate_instances_draft(instances: tuple[InstanceDraft, ...]) -> None:
    """Reject empty or duplicated instance values before saving.

    Whitespace-only values count as empty without normalizing the stored value.
    Endpoint duplicates are reported with the comparing instance index.
    """

    errors: list[str] = []
    if not instances:
        errors.append("at least one instance is required")
    rpc_owners: dict[str, int] = {}
    event_owners: dict[str, int] = {}
    for index, instance in enumerate(instances):
        number = index + 1
        if not instance.scenario.strip():
            errors.append(f"Instance {number} has an empty scenario")
        rpc = instance.rpc_endpoint
        if not rpc.strip():
            errors.append(f"Instance {number} has an empty RPC endpoint")
        elif rpc in rpc_owners:
            errors.append(
                f"Instance {number} uses the same RPC endpoint as "
                f"Instance {rpc_owners[rpc] + 1}."
            )
        else:
            rpc_owners[rpc] = index
        event = instance.event_endpoint
        if not event.strip():
            errors.append(f"Instance {number} has an empty event endpoint")
        elif event in event_owners:
            errors.append(
                f"Instance {number} uses the same event endpoint as "
                f"Instance {event_owners[event] + 1}."
            )
        else:
            event_owners[event] = index
    if errors:
        raise ValueError("\n".join(errors))


def configuration_from_draft(draft: SettingsDraft) -> ApplicationConfiguration:
    """Build a validated configuration from current draft values."""

    validate_instances_draft(draft.instances)
    instances = tuple(
        InstanceConfiguration(
            connection=LiveSplitConnection(
                instance.rpc_endpoint,
                instance.event_endpoint,
            ),
            scenario=instance.scenario,
        )
        for instance in draft.instances
    )
    return ApplicationConfiguration(
        version=1,
        source=_configuration_source(draft.source),
        instances=instances,
        runtime=RuntimeConfiguration(draft.log_level),
    )


@dataclass(frozen=True)
class EditPermission:
    """Which draft fields may be edited for a given session phase."""

    source: bool
    instances: bool
    log_level: bool


def edit_permission(*, active: bool) -> EditPermission:
    """Resolve editability from whether a session is currently in progress.

    Source and every instance are disabled while active so an in-flight session
    never changes its input or its scenarios and LiveSplit connections. Log
    level stays editable and is reflected to the active diagnostics on
    confirmation.
    """

    return EditPermission(
        source=not active,
        instances=not active,
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


def _configuration_source(
    source: SourceConfiguration | CameraSourceDraft,
) -> SourceConfiguration:
    if isinstance(source, CameraSourceDraft):
        if source.mode is None:
            raise ValueError("a camera capture mode must be selected")
        return CameraSourceConfiguration(source.device, source.mode)
    return source


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

    def _replace_instance(
        self,
        index: int,
        **changes: object,
    ) -> SettingsDraft | None:
        if self._draft is None:
            return None
        instances = self._draft.instances
        if index < 0 or index >= len(instances):
            return self._draft
        instance = instances[index]
        self._draft = replace(
            self._draft,
            instances=(
                instances[:index]
                + (replace(instance, **changes),)
                + instances[index + 1 :]
            ),
        )
        return self._draft

    def set_instance_scenario(self, index: int, scenario: str) -> SettingsDraft | None:
        return self._replace_instance(index, scenario=scenario)

    def set_instance_rpc_endpoint(
        self,
        index: int,
        endpoint: str,
    ) -> SettingsDraft | None:
        return self._replace_instance(index, rpc_endpoint=endpoint)

    def set_instance_event_endpoint(
        self,
        index: int,
        endpoint: str,
    ) -> SettingsDraft | None:
        return self._replace_instance(index, event_endpoint=endpoint)

    def add_instance(self) -> SettingsDraft | None:
        if self._draft is None:
            return None
        self._draft = replace(
            self._draft,
            instances=self._draft.instances + (InstanceDraft("", "", ""),),
        )
        return self._draft

    def remove_instance(self, index: int) -> SettingsDraft | None:
        if self._draft is None:
            return None
        instances = self._draft.instances
        if index < 0 or index >= len(instances):
            return self._draft
        self._draft = replace(
            self._draft,
            instances=instances[:index] + instances[index + 1 :],
        )
        return self._draft

    def set_log_level(self, level: str) -> SettingsDraft | None:
        if self._draft is None:
            return None
        self._draft = replace(self._draft, log_level=level)
        return self._draft

    def set_camera_device(
        self, backend: CameraBackend, name: str, index: int
    ) -> SettingsDraft | None:
        if self._draft is None:
            return None
        camera = camera_source(self._draft)
        if camera is None:
            return self._draft
        self._draft = replace(
            self._draft,
            source=CameraSourceDraft(
                CameraDeviceConfiguration(backend, name, index), None
            ),
        )
        return self._draft

    def set_camera_mode(self, mode: CameraModeConfiguration) -> SettingsDraft | None:
        if self._draft is None:
            return None
        camera = camera_source(self._draft)
        if camera is None:
            return self._draft
        self._draft = replace(
            self._draft,
            source=CameraSourceDraft(camera.device, mode),
        )
        return self._draft

    def configuration(self) -> ApplicationConfiguration | None:
        if self._draft is None:
            return None
        return configuration_from_draft(self._draft)
