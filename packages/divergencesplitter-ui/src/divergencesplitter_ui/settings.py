"""Editable configuration state and conversion to validated runtime values."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from divergencesplitter.livesplit.models import LiveSplitConnection
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    CropConfiguration,
    InstanceConfiguration,
    ResizeConfiguration,
    RuntimeConfiguration,
    SourceConfiguration,
    SourceTransformConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_device,
)

from divergencesplitter_ui.session import SessionState

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class SourceType(StrEnum):
    CAMERA = "camera"
    VIDEO = "video"


SOURCE_TYPE_LABELS = {SourceType.CAMERA: "Camera", SourceType.VIDEO: "Video File"}
SOURCE_TYPE_BY_LABEL = {
    label: source_type for source_type, label in SOURCE_TYPE_LABELS.items()
}


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
    @property
    def name(self) -> str: ...
    @property
    def backend(self) -> object: ...
    @property
    def index(self) -> int: ...
    @property
    def modes(self) -> Sequence[CameraMode]: ...


class CameraEnumerator(Protocol):
    def list_devices(self) -> Sequence[CameraDevice]: ...


class WindowsCameraEnumerator:
    def list_devices(self) -> Sequence[CameraDevice]:
        return importlib.import_module("windows_capture_device_list").list_devices()


def select_configured_camera(
    configured: CameraDeviceConfiguration, devices: Sequence[CameraDevice]
) -> CameraDevice | None:
    try:
        selected = resolve_camera_device(configured, devices)
    except SourceConfigurationError:
        return None
    return next(device for device in devices if device is selected)


@dataclass
class EditableCameraSourceConfiguration:
    device: CameraDeviceConfiguration | None
    mode: CameraModeConfiguration | None
    request_60_fps: bool


@dataclass
class EditableVideoSourceConfiguration:
    path: str


@dataclass
class EditableCropConfiguration:
    left: int
    right: int
    top: int
    bottom: int


@dataclass
class EditableResizeConfiguration:
    width: int
    height: int


@dataclass
class EditableSourceTransform:
    crop: EditableCropConfiguration | None = None
    resize: EditableResizeConfiguration | None = None


@dataclass
class EditableSourceSettings:
    selected_type: SourceType
    camera: EditableCameraSourceConfiguration
    video: EditableVideoSourceConfiguration
    transform: EditableSourceTransform = field(default_factory=EditableSourceTransform)


@dataclass
class EditableInstanceConfiguration:
    rpc_endpoint: str
    event_endpoint: str
    scenario: str


@dataclass
class EditableApplicationConfiguration:
    configuration_path: Path
    source: EditableSourceSettings
    instances: tuple[EditableInstanceConfiguration, ...]
    log_level: str


def editable_from_configuration(
    configuration: ApplicationConfiguration, path: Path
) -> EditableApplicationConfiguration:
    source = configuration.source
    if isinstance(source, CameraSourceConfiguration):
        source_settings = EditableSourceSettings(
            SourceType.CAMERA,
            EditableCameraSourceConfiguration(
                source.device, source.mode, source.request_60_fps
            ),
            EditableVideoSourceConfiguration(""),
            _editable_transform(source.transform),
        )
    else:
        source_settings = EditableSourceSettings(
            SourceType.VIDEO,
            EditableCameraSourceConfiguration(None, None, False),
            EditableVideoSourceConfiguration(source.path),
            _editable_transform(source.transform),
        )
    return EditableApplicationConfiguration(
        path,
        source_settings,
        tuple(
            EditableInstanceConfiguration(
                i.connection.rpc_endpoint, i.connection.event_endpoint, i.scenario
            )
            for i in configuration.instances
        ),
        configuration.runtime.log_level,
    )


def camera_source(
    editable: EditableApplicationConfiguration,
) -> EditableCameraSourceConfiguration | None:
    return (
        editable.source.camera
        if editable.source.selected_type is SourceType.CAMERA
        else None
    )


def _editable_transform(
    transform: SourceTransformConfiguration,
) -> EditableSourceTransform:
    return EditableSourceTransform(
        None
        if transform.crop is None
        else EditableCropConfiguration(
            transform.crop.left,
            transform.crop.right,
            transform.crop.top,
            transform.crop.bottom,
        ),
        None
        if transform.resize is None
        else EditableResizeConfiguration(
            transform.resize.width, transform.resize.height
        ),
    )


def _configuration_transform(
    transform: EditableSourceTransform,
) -> SourceTransformConfiguration:
    try:
        crop = (
            None
            if transform.crop is None
            else CropConfiguration(
                transform.crop.left,
                transform.crop.right,
                transform.crop.top,
                transform.crop.bottom,
            )
        )
        resize = (
            None
            if transform.resize is None
            else ResizeConfiguration(transform.resize.width, transform.resize.height)
        )
    except (TypeError, ValueError) as error:
        raise ValueError(str(error)) from error
    return SourceTransformConfiguration(crop, resize)


def validate_instances_draft(
    instances: tuple[EditableInstanceConfiguration, ...],
) -> None:
    errors: list[str] = []
    if not instances:
        errors.append("at least one instance is required")
    rpc_owners: dict[str, int] = {}
    event_owners: dict[str, int] = {}
    for index, instance in enumerate(instances):
        number = index + 1
        if not instance.scenario.strip():
            errors.append(f"Instance {number} has an empty scenario")
        for value, label, owners in (
            (instance.rpc_endpoint, "RPC endpoint", rpc_owners),
            (instance.event_endpoint, "event endpoint", event_owners),
        ):
            if not value.strip():
                errors.append(f"Instance {number} has an empty {label}")
            elif value in owners:
                errors.append(
                    f"Instance {number} uses the same {label} as Instance {owners[value] + 1}."
                )
            else:
                owners[value] = index
    if errors:
        raise ValueError("\n".join(errors))


def configuration_from_editable(
    editable: EditableApplicationConfiguration,
) -> ApplicationConfiguration:
    validate_instances_draft(editable.instances)
    source_settings = editable.source
    if source_settings.selected_type is SourceType.CAMERA:
        camera = source_settings.camera
        if camera.device is None:
            raise ValueError("a camera device must be selected")
        if camera.mode is None:
            raise ValueError("a camera capture mode must be selected")
        source: SourceConfiguration = CameraSourceConfiguration(
            camera.device,
            camera.mode,
            camera.request_60_fps,
            _configuration_transform(source_settings.transform),
        )
    elif source_settings.selected_type is SourceType.VIDEO:
        path = source_settings.video.path
        if not path.strip():
            raise ValueError("a video file must be selected")
        source = VideoSourceConfiguration(
            path, _configuration_transform(source_settings.transform)
        )
    else:  # pragma: no cover - protects future source additions
        raise ValueError(f"unsupported source type: {source_settings.selected_type}")
    return ApplicationConfiguration(
        version=1,
        source=source,
        instances=tuple(
            InstanceConfiguration(
                LiveSplitConnection(i.rpc_endpoint, i.event_endpoint), i.scenario
            )
            for i in editable.instances
        ),
        runtime=RuntimeConfiguration(editable.log_level),
    )


@dataclass(frozen=True)
class EditPermission:
    source: bool
    instances: bool
    log_level: bool


def edit_permission(state: SessionState) -> EditPermission:
    editable = state not in {
        SessionState.LOADING,
        SessionState.CONNECTING,
        SessionState.STOPPING,
    }
    return EditPermission(editable, editable, editable)


class SettingsModel:
    def __init__(self, camera_enumerator: CameraEnumerator) -> None:
        self._camera_enumerator = camera_enumerator
        self._editable: EditableApplicationConfiguration | None = None
        self._dirty = False

    @property
    def editable(self) -> EditableApplicationConfiguration | None:
        return self._editable

    @property
    def draft(self) -> EditableApplicationConfiguration | None:
        return self._editable

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def open_configuration(
        self, configuration: ApplicationConfiguration, path: Path
    ) -> EditableApplicationConfiguration:
        self._editable = editable_from_configuration(configuration, path)
        self._dirty = False
        return self._editable

    def create_default_configuration(
        self, path: Path
    ) -> EditableApplicationConfiguration:
        self._editable = EditableApplicationConfiguration(
            path,
            EditableSourceSettings(
                SourceType.CAMERA,
                EditableCameraSourceConfiguration(None, None, False),
                EditableVideoSourceConfiguration(""),
                EditableSourceTransform(),
            ),
            (),
            "INFO",
        )
        self._dirty = True
        return self._editable

    def create_default_camera_configuration(
        self,
        path: Path,
        device: CameraDeviceConfiguration,
        mode: CameraModeConfiguration | None = None,
    ) -> EditableApplicationConfiguration:
        editable = self.create_default_configuration(path)
        editable.source.camera.device = device
        editable.source.camera.mode = mode
        return editable

    def mark_saved(
        self, path: Path | None = None
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        if path is not None:
            self._editable.configuration_path = path
        self._dirty = False
        return self._editable

    def list_cameras(self) -> Sequence[CameraDevice]:
        return self._camera_enumerator.list_devices()

    def _changed(self, before: object, after: object) -> None:
        if before != after:
            self._dirty = True

    def set_source_type(
        self, source_type: SourceType
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        before = self._editable.source.selected_type
        self._editable.source.selected_type = source_type
        self._changed(before, source_type)
        return self._editable

    def set_video_path(self, path: str) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        before = self._editable.source.video.path
        self._editable.source.video.path = path
        self._changed(before, path)
        return self._editable

    def set_crop(
        self, crop: EditableCropConfiguration | None
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        before = self._editable.source.transform.crop
        self._editable.source.transform.crop = crop
        self._changed(before, crop)
        return self._editable

    def set_resize(
        self, resize: EditableResizeConfiguration | None
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        before = self._editable.source.transform.resize
        self._editable.source.transform.resize = resize
        self._changed(before, resize)
        return self._editable

    def set_crop_values(
        self, left: int, right: int, top: int, bottom: int
    ) -> EditableApplicationConfiguration | None:
        return self.set_crop(EditableCropConfiguration(left, right, top, bottom))

    def set_resize_values(
        self, width: int, height: int
    ) -> EditableApplicationConfiguration | None:
        return self.set_resize(EditableResizeConfiguration(width, height))

    def set_camera_device(
        self, backend: CameraBackend, name: str, index: int
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        camera = self._editable.source.camera
        value = CameraDeviceConfiguration(backend, name, index)
        changed = camera.device != value
        self._changed(camera.device, value)
        if changed:
            camera.device, camera.mode = value, None
        return self._editable

    def set_camera_mode(
        self, mode: CameraModeConfiguration
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        camera = self._editable.source.camera
        self._changed(camera.mode, mode)
        camera.mode = mode
        return self._editable

    def set_request_60_fps(
        self, enabled: bool
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        camera = self._editable.source.camera
        self._changed(camera.request_60_fps, enabled)
        camera.request_60_fps = enabled
        return self._editable

    def _replace_instance(
        self, index: int, **changes: str
    ) -> EditableApplicationConfiguration | None:
        if self._editable is None or not 0 <= index < len(self._editable.instances):
            return self._editable
        instance = self._editable.instances[index]
        updated = replace(instance, **changes)
        self._changed(instance, updated)
        self._editable.instances = (
            self._editable.instances[:index]
            + (updated,)
            + self._editable.instances[index + 1 :]
        )
        return self._editable

    def set_instance_scenario(
        self, index: int, scenario: str
    ) -> EditableApplicationConfiguration | None:
        return self._replace_instance(index, scenario=scenario)

    def set_instance_rpc_endpoint(
        self, index: int, endpoint: str
    ) -> EditableApplicationConfiguration | None:
        return self._replace_instance(index, rpc_endpoint=endpoint)

    def set_instance_event_endpoint(
        self, index: int, endpoint: str
    ) -> EditableApplicationConfiguration | None:
        return self._replace_instance(index, event_endpoint=endpoint)

    def add_instance(self) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        self._editable.instances += (EditableInstanceConfiguration("", "", ""),)
        self._dirty = True
        return self._editable

    def remove_instance(self, index: int) -> EditableApplicationConfiguration | None:
        if self._editable is None or not 0 <= index < len(self._editable.instances):
            return self._editable
        self._editable.instances = (
            self._editable.instances[:index] + self._editable.instances[index + 1 :]
        )
        self._dirty = True
        return self._editable

    def set_log_level(self, level: str) -> EditableApplicationConfiguration | None:
        if self._editable is None:
            return None
        self._changed(self._editable.log_level, level)
        self._editable.log_level = level
        return self._editable

    def configuration(self) -> ApplicationConfiguration | None:
        return (
            configuration_from_editable(self._editable)
            if self._editable is not None
            else None
        )


# Temporary import aliases keep integrations using the former public names source-compatible.
CameraSourceDraft = EditableCameraSourceConfiguration
InstanceDraft = EditableInstanceConfiguration
SettingsDraft = EditableApplicationConfiguration
draft_from_configuration = editable_from_configuration
configuration_from_draft = configuration_from_editable
