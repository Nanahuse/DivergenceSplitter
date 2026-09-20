"""Input source section for the Flet Configuration page.

The section only writes user choices into the shared ``SettingsModel`` and reads
the draft back into its controls; it never opens devices or starts previews.
Camera enumeration, modes, and NDI discovery reuse the existing model helpers
and ``NdiDiscovery`` rather than re-implementing platform access here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import flet as ft
from divergencesplitter_runtime.configuration.models import (
    CameraModeConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_mode,
)

from divergencesplitter_ui.configuration.dialogs import VIDEO_EXTENSIONS, FileDialogs
from divergencesplitter_ui.ndi_branding import NDI_TRADEMARK_NOTICE, NDI_WEBSITE_URL
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.settings import (
    SOURCE_TYPE_LABELS,
    CameraDevice,
    CameraMode,
    EditableProfile,
    EditPermission,
    SettingsModel,
    SourceType,
    camera_backend,
    camera_device_label,
    camera_mode_label,
    camera_source,
    ndi_source,
    select_configured_camera,
)


def source_type_options(ndi_available: bool) -> list[ft.DropdownOption]:
    options = [
        ft.DropdownOption(key=SOURCE_TYPE_LABELS[SourceType.CAMERA]),
        ft.DropdownOption(key=SOURCE_TYPE_LABELS[SourceType.VIDEO]),
    ]
    if ndi_available:
        options.append(ft.DropdownOption(key=SOURCE_TYPE_LABELS[SourceType.NDI]))
    else:
        options.append(
            ft.DropdownOption(
                key=f"{SOURCE_TYPE_LABELS[SourceType.NDI]} (Unavailable)",
                disabled=True,
            )
        )
    return options


class SourceSection:
    """Edit source type, camera, video, and NDI draft settings."""

    def __init__(
        self,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        on_input_changed: Callable[[], None],
        ndi_discovery: NdiDiscovery | None = None,
    ) -> None:
        self._model = model
        self._dialogs = dialogs
        self._on_input_changed = on_input_changed
        self._ndi_discovery = (
            ndi_discovery if ndi_discovery is not None else NdiDiscovery()
        )
        self._camera_by_label: dict[str, CameraDevice] = {}
        self._mode_by_label: dict[str, CameraMode] = {}
        self._ndi_item_names: dict[str, str] = {}
        self._device_label: str | None = None
        self._devices: tuple[CameraDevice, ...] = ()
        self._applied_ndi_support: bool | None = None
        self._applied_ndi_sources: tuple[str, ...] | None = None
        self._applied_ndi_configured: str | None = None
        self._applied_source_type: SourceType | None = None

        self._source_type = ft.Dropdown(
            label="Source type",
            options=source_type_options(False),
            value=SOURCE_TYPE_LABELS[SourceType.CAMERA],
            on_select=self._on_source_type_selected,
            key="profile-source-type",
        )
        self._device = ft.Dropdown(
            label="Camera",
            options=[],
            on_select=self._on_device_selected,
        )
        self._camera_note = ft.Text("")
        self._mode = ft.Dropdown(
            label="Capture mode",
            options=[],
            on_select=self._on_mode_selected,
        )
        self._request_60_fps = ft.Switch(
            label="Request 60 FPS",
            value=False,
            on_change=self._on_request_60_fps_changed,
        )
        self._camera_group = ft.Column(
            controls=[
                ft.Text("Camera"),
                self._device,
                self._camera_note,
                self._mode,
                self._request_60_fps,
            ],
            spacing=4,
        )

        self._video_path = ft.TextField(
            label="Video file",
            value="",
            on_change=self._on_video_path_changed,
            expand=True,
            key="profile-video-path",
        )
        self._video_group = ft.Row(
            controls=[
                self._video_path,
                ft.OutlinedButton(content="Browse...", on_click=self._on_browse_video),
            ],
            spacing=8,
        )

        self._ndi_source = ft.Dropdown(
            label="NDI® source",
            options=[],
            on_select=self._on_ndi_source_selected,
        )
        self._ndi_status = ft.Text("")
        self._ndi_group = ft.Column(
            controls=[
                ft.Text("NDI® source"),
                self._ndi_source,
                self._ndi_status,
                ft.OutlinedButton(content="Refresh", on_click=self._on_refresh_ndi),
                ft.TextButton(content="Learn about NDI ↗", url=NDI_WEBSITE_URL),
                ft.Text(NDI_TRADEMARK_NOTICE, size=11),
            ],
            spacing=4,
        )

        self._control = ft.Column(
            controls=[
                ft.Text("Input source"),
                self._source_type,
                self._camera_group,
                self._video_group,
                self._ndi_group,
            ],
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def type_dropdown(self) -> ft.Dropdown:
        """The Source type selector, exposed for read-only UI assertions."""

        return self._source_type

    @property
    def video_path_field(self) -> ft.TextField:
        """The Video file path field, exposed for read-only UI assertions."""

        return self._video_path

    @property
    def device_dropdown(self) -> ft.Dropdown:
        """The Camera device selector, exposed for read-only UI assertions."""

        return self._device

    @property
    def mode_dropdown(self) -> ft.Dropdown:
        """The camera Capture mode selector, exposed for read-only assertions."""

        return self._mode

    def refresh_ndi(self) -> None:
        self._ndi_discovery.refresh()

    def stop_ndi(self) -> None:
        self._ndi_discovery.join(2.0)

    def populate(self, draft: EditableProfile) -> None:
        """Refresh camera modes and NDI sources from the draft."""

        self._video_path.value = draft.source.video.path
        camera = camera_source(draft)
        if camera is not None:
            self._populate_cameras(camera.device, camera.mode)
        ndi = ndi_source(draft)
        if ndi is not None:
            self._populate_ndi(ndi.name, self._ndi_discovery.sources())
            self._applied_ndi_sources = self._ndi_discovery.sources()
            self._applied_ndi_configured = ndi.name

    def apply(
        self,
        draft: EditableProfile,
        permission: EditPermission,
    ) -> bool:
        """Sync values and enablement from the draft; return whether it changed."""

        changed = False
        support = self._ndi_discovery.support()
        ndi_available = bool(support is not None and support.available)
        if ndi_available != self._applied_ndi_support:
            self._applied_ndi_support = ndi_available
            self._model.set_ndi_available(ndi_available)
            self._source_type.options = source_type_options(ndi_available)
            changed = True

        display_label = SOURCE_TYPE_LABELS[draft.source.selected_type]
        if (
            draft.source.selected_type is SourceType.NDI
            and not ndi_available
            and self._applied_ndi_support is False
        ):
            display_label = f"{SOURCE_TYPE_LABELS[SourceType.NDI]} (Unavailable)"
        if self._source_type.value != display_label:
            self._source_type.value = display_label
            changed = True
        if self._applied_source_type is not draft.source.selected_type:
            self._applied_source_type = draft.source.selected_type
            self._show_group(draft.source.selected_type)
            changed = True

        if self._video_path.value != draft.source.video.path:
            self._video_path.value = draft.source.video.path
            changed = True

        camera = camera_source(draft)
        if camera is not None and self._request_60_fps.value != camera.request_60_fps:
            self._request_60_fps.value = camera.request_60_fps
            changed = True

        sources = self._ndi_discovery.sources()
        ndi = ndi_source(draft)
        configured = ndi.name if ndi is not None else ""
        if (
            sources != self._applied_ndi_sources
            or configured != self._applied_ndi_configured
        ):
            self._applied_ndi_sources = sources
            self._applied_ndi_configured = configured
            self._populate_ndi(configured, sources)
            changed = True
        status = self._ndi_status_text(support, configured, sources)
        if self._ndi_status.value != status:
            self._ndi_status.value = status
            changed = True

        for control, enabled in (
            (self._source_type, permission.source),
            (self._device, permission.source),
            (self._mode, permission.source),
            (self._request_60_fps, permission.source),
            (self._video_path, permission.source),
            (self._ndi_source, permission.source),
        ):
            if control.disabled == enabled:
                control.disabled = not enabled
                changed = True
        return changed

    def _show_group(self, source_type: SourceType) -> None:
        self._camera_group.visible = source_type is SourceType.CAMERA
        self._video_group.visible = source_type is SourceType.VIDEO
        self._ndi_group.visible = source_type is SourceType.NDI

    def _ndi_status_text(self, support, configured: str, sources: Sequence[str]) -> str:
        if support is not None and not support.available:
            return "NDI support is not available on this system."
        if configured and configured not in sources:
            return f'Waiting for NDI source "{configured}".'
        return ""

    def _populate_cameras(self, configured_device, configured_mode) -> None:
        self._camera_by_label = {}
        try:
            devices = tuple(self._model.list_cameras())
        except Exception as error:  # noqa: BLE001 - enumeration failure
            self._camera_note.value = f"could not enumerate cameras: {error}"
            self._device.options = []
            self._device.value = None
            self._mode.options = []
            self._mode.value = None
            self._devices = ()
            return
        self._devices = devices
        self._device.options = [
            ft.DropdownOption(key=camera_device_label(device)) for device in devices
        ]
        for device in devices:
            self._camera_by_label[camera_device_label(device)] = device
        selected = (
            select_configured_camera(configured_device, devices)
            if configured_device is not None
            else None
        )
        if selected is None:
            self._camera_note.value = (
                "" if configured_device is None else "configured camera is unavailable"
            )
            self._device.value = None
            self._mode.options = []
            self._mode.value = None
            return
        self._camera_note.value = ""
        self._device.value = camera_device_label(selected)
        self._populate_modes(selected, configured_mode)

    def _populate_modes(self, device: CameraDevice, configured_mode) -> None:
        self._mode_by_label = {}
        self._mode.options = [
            ft.DropdownOption(key=camera_mode_label(mode)) for mode in device.modes
        ]
        for mode in device.modes:
            self._mode_by_label[camera_mode_label(mode)] = mode
        selected = ""
        if configured_mode is not None:
            try:
                resolved = resolve_camera_mode(configured_mode, device.modes)
            except SourceConfigurationError:
                self._camera_note.value = "configured capture mode is unavailable"
                self._mode.value = None
                return
            selected = camera_mode_label(resolved)
        self._mode.value = selected or None

    def _populate_ndi(self, configured: str, discovered: Sequence[str]) -> None:
        options = [ft.DropdownOption(key=name) for name in discovered]
        mapping = {name: name for name in discovered}
        if configured and configured not in discovered:
            label = f"{configured} (Unavailable)"
            options.append(ft.DropdownOption(key=label))
            mapping[label] = configured
        self._ndi_item_names = mapping
        self._ndi_source.options = options
        self._ndi_source.value = next(
            (label for label, name in mapping.items() if name == configured), None
        )

    def _on_source_type_selected(self, event: ft.Event[ft.Dropdown]) -> None:
        if self._model.draft is None:
            return
        label = self._source_type.value
        source_type = {
            SOURCE_TYPE_LABELS[SourceType.CAMERA]: SourceType.CAMERA,
            SOURCE_TYPE_LABELS[SourceType.VIDEO]: SourceType.VIDEO,
            SOURCE_TYPE_LABELS[SourceType.NDI]: SourceType.NDI,
        }.get(label)
        if source_type is None:
            return
        if self._model.set_source_type(source_type) is None:
            return
        self._show_group(source_type)
        self._on_input_changed()
        if source_type is SourceType.NDI:
            self._ndi_discovery.refresh()

    def _on_device_selected(self, event: ft.Event[ft.Dropdown]) -> None:
        device = self._camera_by_label.get(self._device.value or "")
        if device is None or self._model.draft is None:
            return
        self._model.set_camera_device(
            camera_backend(device.backend), device.name, device.index
        )
        self._populate_modes(device, None)
        self._on_input_changed()

    def _on_mode_selected(self, event: ft.Event[ft.Dropdown]) -> None:
        mode = self._mode_by_label.get(self._mode.value or "")
        if mode is None:
            return
        self._model.set_camera_mode(
            CameraModeConfiguration(
                mode.width, mode.height, mode.fps, mode.subtype_guid
            )
        )
        self._on_input_changed()

    def _on_request_60_fps_changed(self, event: ft.Event[ft.Switch]) -> None:
        self._model.set_request_60_fps(bool(self._request_60_fps.value))
        self._on_input_changed()

    def _on_video_path_changed(self, event: ft.Event[ft.TextField]) -> None:
        self._model.set_video_path(self._video_path.value)

    async def _on_browse_video(self, event: ft.Event[ft.OutlinedButton]) -> None:
        path = await self._dialogs.open_file(
            title="Select video file", extensions=VIDEO_EXTENSIONS
        )
        if path is None:
            return
        self._model.set_video_path(str(path))
        self._video_path.value = str(path)
        try:
            self._video_path.update()
        except RuntimeError:
            pass

    def _on_ndi_source_selected(self, event: ft.Event[ft.Dropdown]) -> None:
        name = self._ndi_item_names.get(self._ndi_source.value or "")
        if name is None:
            return
        self._model.set_ndi_source_name(name)
        self._on_input_changed()

    def _on_refresh_ndi(self, event: ft.Event[ft.OutlinedButton]) -> None:
        self._ndi_discovery.refresh()
