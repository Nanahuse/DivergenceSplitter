"""Editable Profile and App Settings state with projection to validated values.

The editable state is split by responsibility: :class:`EditableProfile` owns the
source, instances, and Profile path, while the App Settings state owns the log
level, reaction time, and theme. ``SettingsModel`` keeps the *applied* App
Settings and the *draft* the settings screen is editing apart, so App Settings
edits never mark the Profile dirty and are only persisted on an explicit Apply.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from divergencesplitter.livesplit.models import LiveSplitConnection
from divergencesplitter_runtime.configuration.models import (
    APP_SETTINGS_VERSION,
    AppSettings,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    CropConfiguration,
    InstanceConfiguration,
    NdiSourceConfiguration,
    Profile,
    ResizeConfiguration,
    ResizeInterpolation,
    SourceConfiguration,
    SourceTransformConfiguration,
    Theme,
    UiSettings,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_device,
)

from divergencesplitter_ui.session import SessionState

LOG_LEVELS = ("OFF", "DEBUG")


class SourceType(StrEnum):
    CAMERA = "camera"
    VIDEO = "video"
    NDI = "ndi"


SOURCE_TYPE_LABELS = {
    SourceType.CAMERA: "Camera",
    SourceType.VIDEO: "Video File",
    SourceType.NDI: "NDI",
}
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


def camera_backend_value(backend: object) -> str:
    """Return a device backend as its lowercase ``CameraBackend`` value."""

    value = getattr(backend, "value", None)
    if isinstance(value, str):
        return value
    return str(getattr(backend, "name", "")).lower()


def camera_backend(backend: object) -> CameraBackend:
    return CameraBackend(camera_backend_value(backend))


def camera_backend_display(backend: str) -> str:
    return {
        "direct_show": "DirectShow",
        "media_foundation": "Media Foundation",
    }.get(backend, backend)


def camera_device_label(device: CameraDevice) -> str:
    return (
        f"[{camera_backend_display(camera_backend_value(device.backend))}] "
        f"{device.name} (index {device.index})"
    )


def camera_mode_label(mode: CameraMode) -> str:
    format_value = getattr(mode, "format", None) or getattr(mode, "subtype_guid", "")
    return f"{mode.width} × {mode.height} @ {mode.fps:g} fps — {format_value}"


@dataclass
class EditableCameraSourceConfiguration:
    device: CameraDeviceConfiguration | None
    mode: CameraModeConfiguration | None
    request_60_fps: bool


@dataclass
class EditableVideoSourceConfiguration:
    path: str


@dataclass
class EditableNdiSourceConfiguration:
    name: str


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
    interpolation: ResizeInterpolation = ResizeInterpolation.AREA
    resize_references: bool = False


@dataclass
class EditableSourceTransform:
    crop: EditableCropConfiguration | None = None
    resize: EditableResizeConfiguration | None = None


@dataclass
class EditableSourceSettings:
    selected_type: SourceType
    camera: EditableCameraSourceConfiguration
    video: EditableVideoSourceConfiguration
    ndi: EditableNdiSourceConfiguration
    transform: EditableSourceTransform = field(default_factory=EditableSourceTransform)


@dataclass
class EditableInstanceConfiguration:
    rpc_endpoint: str
    event_endpoint: str
    scenario: str


@dataclass
class EditableProfile:
    """The editable Profile draft: its path, source, and instances only.

    Log level and reaction time are App Settings, so they are deliberately not
    fields here and never make a Profile dirty.
    """

    profile_path: Path
    source: EditableSourceSettings
    instances: tuple[EditableInstanceConfiguration, ...]


@dataclass
class EditableAppSettings:
    """A validated, currently applied App Settings value."""

    log_level: str = "OFF"
    reaction_time_ms: int = 0
    theme: Theme = Theme.LIGHT


@dataclass
class AppSettingsDraft:
    """The App Settings values the settings screen is editing.

    Reaction time is kept as the raw text the user typed so partial or invalid
    input survives every periodic sync; it is parsed and validated only when the
    settings are accepted by an explicit Apply.
    """

    theme: Theme = Theme.LIGHT
    log_level: str = "OFF"
    reaction_time_text: str = "0"


def editable_profile_from(configuration: Profile, path: Path) -> EditableProfile:
    source = configuration.source
    match source:
        case CameraSourceConfiguration():
            source_settings = EditableSourceSettings(
                SourceType.CAMERA,
                EditableCameraSourceConfiguration(
                    source.device, source.mode, source.request_60_fps
                ),
                EditableVideoSourceConfiguration(""),
                EditableNdiSourceConfiguration(""),
                _editable_transform(source.transform),
            )
        case VideoSourceConfiguration():
            source_settings = EditableSourceSettings(
                SourceType.VIDEO,
                EditableCameraSourceConfiguration(None, None, False),
                EditableVideoSourceConfiguration(source.path),
                EditableNdiSourceConfiguration(""),
                _editable_transform(source.transform),
            )
        case NdiSourceConfiguration():
            source_settings = EditableSourceSettings(
                SourceType.NDI,
                EditableCameraSourceConfiguration(None, None, False),
                EditableVideoSourceConfiguration(""),
                EditableNdiSourceConfiguration(source.name),
                _editable_transform(source.transform),
            )
        case _:  # pragma: no cover - protects future source additions
            raise ValueError(f"unsupported source: {source!r}")
    return EditableProfile(
        path,
        source_settings,
        tuple(
            EditableInstanceConfiguration(
                i.connection.rpc_endpoint, i.connection.event_endpoint, i.scenario
            )
            for i in configuration.instances
        ),
    )


def camera_source(
    editable: EditableProfile,
) -> EditableCameraSourceConfiguration | None:
    return (
        editable.source.camera
        if editable.source.selected_type is SourceType.CAMERA
        else None
    )


def ndi_source(
    editable: EditableProfile,
) -> EditableNdiSourceConfiguration | None:
    return (
        editable.source.ndi if editable.source.selected_type is SourceType.NDI else None
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
            transform.resize.width,
            transform.resize.height,
            transform.resize.interpolation,
            transform.resize.resize_references,
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
            else ResizeConfiguration(
                transform.resize.width,
                transform.resize.height,
                transform.resize.interpolation,
                transform.resize.resize_references,
            )
        )
    except (TypeError, ValueError) as error:
        raise ValueError(str(error)) from error
    return SourceTransformConfiguration(crop, resize)


def source_transform_from_editable(
    editable: EditableProfile,
) -> SourceTransformConfiguration:
    """Project the draft crop/resize into a validated transform configuration."""

    return _configuration_transform(editable.source.transform)


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


def profile_from_editable(
    editable: EditableProfile,
) -> Profile:
    validate_instances_draft(editable.instances)
    source_settings = editable.source
    source: SourceConfiguration
    match source_settings.selected_type:
        case SourceType.CAMERA:
            camera = source_settings.camera
            if camera.device is None:
                raise ValueError("a camera device must be selected")
            if camera.mode is None:
                raise ValueError("a camera capture mode must be selected")
            source = CameraSourceConfiguration(
                camera.device,
                camera.mode,
                camera.request_60_fps,
                _configuration_transform(source_settings.transform),
            )
        case SourceType.VIDEO:
            path = source_settings.video.path
            if not path.strip():
                raise ValueError("a video file must be selected")
            source = VideoSourceConfiguration(
                path, _configuration_transform(source_settings.transform)
            )
        case SourceType.NDI:
            name = source_settings.ndi.name
            if not name.strip():
                raise ValueError("an NDI source must be selected")
            source = NdiSourceConfiguration(
                name, _configuration_transform(source_settings.transform)
            )
        case _:  # pragma: no cover - protects future source additions
            raise ValueError(
                f"unsupported source type: {source_settings.selected_type}"
            )
    return Profile(
        version=1,
        source=source,
        instances=tuple(
            InstanceConfiguration(
                LiveSplitConnection(i.rpc_endpoint, i.event_endpoint), i.scenario
            )
            for i in editable.instances
        ),
    )


@dataclass(frozen=True)
class EditPermission:
    source: bool
    instances: bool
    log_level: bool
    reaction_time: bool
    theme: bool

    @property
    def settings(self) -> bool:
        """Whether the Settings screen, including its Apply button, is editable."""

        return self.theme and self.log_level and self.reaction_time


def edit_permission(state: SessionState) -> EditPermission:
    editable = state not in {
        SessionState.LOADING,
        SessionState.CONNECTING,
        SessionState.STOPPING,
    }
    return EditPermission(editable, editable, editable, editable, editable)


class SettingsModel:
    """Own the editable Profile draft and the App Settings state separately.

    Profile edits drive :attr:`is_dirty`; App Settings edits live in the
    :attr:`app_settings_draft` and never mark the Profile dirty. Only
    :meth:`apply_app_settings` moves the draft into the applied state used by
    :meth:`app_settings_document`. ``last_profile`` is lifecycle-owned: it tracks
    the last Profile that was successfully opened or saved so it can be persisted
    as part of App Settings.
    """

    def __init__(self, camera_enumerator: CameraEnumerator) -> None:
        self._camera_enumerator = camera_enumerator
        self._profile: EditableProfile | None = None
        self._applied_app_settings = EditableAppSettings()
        self._app_settings_draft = AppSettingsDraft()
        self._last_profile: Path | None = None
        self._dirty = False
        self._ndi_available = False

    @property
    def ndi_available(self) -> bool:
        return self._ndi_available

    def set_ndi_available(self, available: bool) -> None:
        self._ndi_available = available

    @property
    def profile(self) -> EditableProfile | None:
        return self._profile

    @property
    def draft(self) -> EditableProfile | None:
        return self._profile

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def applied_app_settings(self) -> EditableAppSettings:
        """The App Settings values that are currently saved and applied."""

        return self._applied_app_settings

    @property
    def app_settings_draft(self) -> AppSettingsDraft:
        """The App Settings values the settings screen is editing."""

        return self._app_settings_draft

    @property
    def app_settings_dirty(self) -> bool:
        """Whether the draft differs from the applied App Settings.

        An unparseable reaction time counts as a change so Apply stays enabled
        and can report the validation error instead of silently ignoring it.
        """

        draft = self._app_settings_draft
        applied = self._applied_app_settings
        if draft.theme is not applied.theme or draft.log_level != applied.log_level:
            return True
        try:
            reaction_time = int(draft.reaction_time_text.strip())
        except TypeError, ValueError:
            return True
        return reaction_time != applied.reaction_time_ms

    @property
    def last_profile(self) -> Path | None:
        return self._last_profile

    def load_app_settings(self, settings: AppSettings) -> None:
        """Seed the applied and draft App Settings from a loaded document."""

        log_level = "OFF" if settings.log_level == "OFF" else "DEBUG"
        self._applied_app_settings = EditableAppSettings(
            log_level,
            settings.reaction_time_ms,
            settings.ui.theme,
        )
        self._app_settings_draft = AppSettingsDraft(
            settings.ui.theme, log_level, str(settings.reaction_time_ms)
        )
        self._last_profile = (
            None if settings.last_profile is None else Path(settings.last_profile)
        )

    def set_last_profile(self, path: Path | None) -> None:
        self._last_profile = None if path is None else Path(path)

    def open_profile(self, profile: Profile, path: Path) -> EditableProfile:
        self._profile = editable_profile_from(profile, path)
        self._dirty = False
        return self._profile

    def create_default_profile(self, path: Path) -> EditableProfile:
        self._profile = EditableProfile(
            path,
            EditableSourceSettings(
                SourceType.CAMERA,
                EditableCameraSourceConfiguration(None, None, False),
                EditableVideoSourceConfiguration(""),
                EditableNdiSourceConfiguration(""),
                EditableSourceTransform(),
            ),
            (),
        )
        self._dirty = True
        return self._profile

    def create_default_camera_profile(
        self,
        path: Path,
        device: CameraDeviceConfiguration,
        mode: CameraModeConfiguration | None = None,
    ) -> EditableProfile:
        editable = self.create_default_profile(path)
        editable.source.camera.device = device
        editable.source.camera.mode = mode
        return editable

    def mark_saved(self, path: Path | None = None) -> EditableProfile | None:
        if self._profile is None:
            return None
        if path is not None:
            self._profile.profile_path = path
        self._dirty = False
        return self._profile

    def list_cameras(self) -> Sequence[CameraDevice]:
        return self._camera_enumerator.list_devices()

    def _changed(self, before: object, after: object) -> None:
        if before != after:
            self._dirty = True

    def set_source_type(self, source_type: SourceType) -> EditableProfile | None:
        if self._profile is None:
            return None
        if source_type is SourceType.NDI and not self._ndi_available:
            return None
        before = self._profile.source.selected_type
        self._profile.source.selected_type = source_type
        self._changed(before, source_type)
        return self._profile

    def set_ndi_source_name(self, name: str) -> EditableProfile | None:
        if self._profile is None:
            return None
        before = self._profile.source.ndi.name
        self._profile.source.ndi.name = name
        self._changed(before, name)
        return self._profile

    def set_video_path(self, path: str) -> EditableProfile | None:
        if self._profile is None:
            return None
        before = self._profile.source.video.path
        self._profile.source.video.path = path
        self._changed(before, path)
        return self._profile

    def set_crop(
        self, crop: EditableCropConfiguration | None
    ) -> EditableProfile | None:
        if self._profile is None:
            return None
        before = self._profile.source.transform.crop
        self._profile.source.transform.crop = crop
        self._changed(before, crop)
        return self._profile

    def set_resize(
        self, resize: EditableResizeConfiguration | None
    ) -> EditableProfile | None:
        if self._profile is None:
            return None
        before = self._profile.source.transform.resize
        self._profile.source.transform.resize = resize
        self._changed(before, resize)
        return self._profile

    def set_crop_values(
        self, left: int, right: int, top: int, bottom: int
    ) -> EditableProfile | None:
        return self.set_crop(EditableCropConfiguration(left, right, top, bottom))

    def set_resize_values(self, width: int, height: int) -> EditableProfile | None:
        current = self._profile.source.transform.resize if self._profile else None
        interpolation = (
            current.interpolation if current is not None else ResizeInterpolation.AREA
        )
        resize_references = current.resize_references if current is not None else False
        return self.set_resize(
            EditableResizeConfiguration(width, height, interpolation, resize_references)
        )

    def set_resize_interpolation(
        self, interpolation: ResizeInterpolation
    ) -> EditableProfile | None:
        if self._profile is None or self._profile.source.transform.resize is None:
            return self._profile
        current = self._profile.source.transform.resize
        return self.set_resize(
            EditableResizeConfiguration(
                current.width, current.height, interpolation, current.resize_references
            )
        )

    def set_resize_references(self, enabled: bool):
        if self._profile is None or self._profile.source.transform.resize is None:
            return self._profile
        current = self._profile.source.transform.resize
        return self.set_resize(
            EditableResizeConfiguration(
                current.width, current.height, current.interpolation, enabled
            )
        )

    def set_camera_device(
        self, backend: CameraBackend, name: str, index: int
    ) -> EditableProfile | None:
        if self._profile is None:
            return None
        camera = self._profile.source.camera
        value = CameraDeviceConfiguration(backend, name, index)
        changed = camera.device != value
        self._changed(camera.device, value)
        if changed:
            camera.device, camera.mode = value, None
        return self._profile

    def set_camera_mode(self, mode: CameraModeConfiguration) -> EditableProfile | None:
        if self._profile is None:
            return None
        camera = self._profile.source.camera
        self._changed(camera.mode, mode)
        camera.mode = mode
        return self._profile

    def set_request_60_fps(self, enabled: bool) -> EditableProfile | None:
        if self._profile is None:
            return None
        camera = self._profile.source.camera
        self._changed(camera.request_60_fps, enabled)
        camera.request_60_fps = enabled
        return self._profile

    def _replace_instance(self, index: int, **changes: str) -> EditableProfile | None:
        if self._profile is None or not 0 <= index < len(self._profile.instances):
            return self._profile
        instance = self._profile.instances[index]
        updated = replace(instance, **changes)
        self._changed(instance, updated)
        self._profile.instances = (
            self._profile.instances[:index]
            + (updated,)
            + self._profile.instances[index + 1 :]
        )
        return self._profile

    def set_instance_scenario(
        self, index: int, scenario: str
    ) -> EditableProfile | None:
        return self._replace_instance(index, scenario=scenario)

    def set_instance_rpc_endpoint(
        self, index: int, endpoint: str
    ) -> EditableProfile | None:
        return self._replace_instance(index, rpc_endpoint=endpoint)

    def set_instance_event_endpoint(
        self, index: int, endpoint: str
    ) -> EditableProfile | None:
        return self._replace_instance(index, event_endpoint=endpoint)

    def add_instance(self) -> EditableProfile | None:
        if self._profile is None:
            return None
        self._profile.instances += (EditableInstanceConfiguration("", "", ""),)
        self._dirty = True
        return self._profile

    def remove_instance(self, index: int) -> EditableProfile | None:
        if self._profile is None or not 0 <= index < len(self._profile.instances):
            return self._profile
        self._profile.instances = (
            self._profile.instances[:index] + self._profile.instances[index + 1 :]
        )
        self._dirty = True
        return self._profile

    def edit_log_level(self, level: str) -> AppSettingsDraft:
        """Update the draft log level; never dirties the Profile or the file."""

        if level not in LOG_LEVELS:
            raise ValueError(f"unsupported logging mode: {level!r}")
        self._app_settings_draft.log_level = level
        return self._app_settings_draft

    def edit_reaction_time(self, text: str) -> AppSettingsDraft:
        """Store raw reaction time input; validation is deferred to Apply."""

        self._app_settings_draft.reaction_time_text = "" if text is None else str(text)
        return self._app_settings_draft

    def edit_theme(self, theme: Theme) -> AppSettingsDraft:
        """Update the draft theme; never dirties the Profile or the file."""

        if not isinstance(theme, Theme):
            raise TypeError(f"unsupported theme: {theme!r}")
        self._app_settings_draft.theme = theme
        return self._app_settings_draft

    def validate_app_settings(self) -> EditableAppSettings:
        """Project the draft into a validated App Settings value.

        Raises :class:`ValueError` when the reaction time is not a non-negative
        integer or a value is otherwise unsupported.
        """

        draft = self._app_settings_draft
        try:
            reaction_time_ms = int(draft.reaction_time_text.strip())
        except (TypeError, ValueError) as error:
            raise ValueError("reaction time must be a non-negative integer") from error
        if reaction_time_ms < 0:
            raise ValueError("reaction time must be a non-negative integer")
        if draft.log_level not in LOG_LEVELS:
            raise ValueError(f"unsupported logging mode: {draft.log_level!r}")
        if not isinstance(draft.theme, Theme):
            raise TypeError(f"unsupported theme: {draft.theme!r}")
        return EditableAppSettings(draft.log_level, reaction_time_ms, draft.theme)

    def apply_app_settings(self, settings: EditableAppSettings) -> None:
        """Commit validated settings as applied and reset the draft to match."""

        self._applied_app_settings = EditableAppSettings(
            settings.log_level, settings.reaction_time_ms, settings.theme
        )
        self._app_settings_draft = AppSettingsDraft(
            settings.theme, settings.log_level, str(settings.reaction_time_ms)
        )

    def profile_document(self) -> Profile | None:
        return (
            profile_from_editable(self._profile) if self._profile is not None else None
        )

    def app_settings_document(
        self, settings: EditableAppSettings | None = None
    ) -> AppSettings:
        """Build the App Settings document; defaults to the applied settings."""

        values = self._applied_app_settings if settings is None else settings
        return AppSettings(
            version=APP_SETTINGS_VERSION,
            log_level=values.log_level,
            reaction_time_ms=values.reaction_time_ms,
            last_profile=(
                None if self._last_profile is None else str(self._last_profile)
            ),
            ui=UiSettings(values.theme),
        )
