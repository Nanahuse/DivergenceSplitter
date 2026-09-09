"""Dear PyGui Configuration page for editing one configuration.

This module imports Dear PyGui and owns every settings widget. It edits the
single ``SettingsModel`` draft shared with the main screen and delegates load,
save, and start to the existing runtime configuration loader, saver, and the
``SessionController``. It never forks a second settings state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_configuration,
    save_configuration,
)
from divergencesplitter_runtime.configuration.models import (
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    CropConfiguration,
    ResizeConfiguration,
    SourceTransformConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_mode,
)

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.camera_preview import CameraPreview
from divergencesplitter_ui.frame_preview import fit_preview
from divergencesplitter_ui.image import (
    TextureEvent,
    flatten,
    plan_texture,
    source_signature,
    to_rgba_float32,
)
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionState,
    is_active,
)
from divergencesplitter_ui.settings import (
    LOG_LEVELS,
    SOURCE_TYPE_BY_LABEL,
    SOURCE_TYPE_LABELS,
    CameraDevice,
    CameraMode,
    EditableApplicationConfiguration,
    InstanceDraft,
    SettingsModel,
    SourceType,
    camera_source,
    edit_permission,
    select_configured_camera,
)
from divergencesplitter_ui.windows_file_dialog import (
    CONFIGURATION_FILTERS,
    VIDEO_FILTERS,
    select_open_file,
    select_open_script_file,
    select_save_file,
)

_CAMERA_LABEL_TEMPLATE = "[{backend}] {name} (index {index})"


@dataclass(frozen=True)
class _InstanceRow:
    """Widget handles for one instance editor."""

    rpc_tag: int | str
    event_tag: int | str
    scenario_tag: int | str
    browse_tag: int | str
    remove_tag: int | str


class ConfigurationPage:
    """Own the Configuration page and drive open/save/start through the draft."""

    PAGE_TAG = "divergence-splitter-configuration-page"

    def __init__(self, controller: SessionController, model: SettingsModel) -> None:
        self._controller = controller
        self._model = model
        self._camera_by_label: dict[str, CameraDevice] = {}
        self._mode_by_label: dict[str, CameraMode] = {}
        self._instance_rows: dict[int, _InstanceRow] = {}
        self._camera_preview = CameraPreview()
        self._preview_texture_tag: int | str | None = None
        self._preview_image_tag: int | str | None = None
        self._preview_signature = None
        self._pending_reload_path: Path | None = None

    def build(self, parent: int | str | None = None) -> None:
        with dpg.group(parent=parent):
            dpg.add_text("Configuration file")
            self._config_path_tag = dpg.add_input_text(
                default_value="",
                width=-1,
                readonly=True,
            )
            with dpg.group(horizontal=True):
                self._new_button_tag = dpg.add_button(
                    label="New...", callback=self._on_new
                )
                self._open_button_tag = dpg.add_button(
                    label="Open...", callback=self._on_open
                )
                self._save_button_tag = dpg.add_button(
                    label="Save", callback=self._on_save
                )
                self._save_as_button_tag = dpg.add_button(
                    label="Save As...", callback=self._on_save_as
                )

            dpg.add_separator()
            dpg.add_text("Input source")
            self._source_type_tag = dpg.add_combo(
                label="Source type",
                items=list(SOURCE_TYPE_LABELS.values()),
                default_value=SOURCE_TYPE_LABELS[SourceType.CAMERA],
                callback=self._on_source_type_changed,
            )
            self._camera_settings_group = dpg.add_group()
            dpg.add_text("Camera", parent=self._camera_settings_group)
            self._camera_tag = dpg.add_combo(
                items=[],
                default_value="",
                width=-1,
                callback=self._on_camera_selected,
                parent=self._camera_settings_group,
            )
            self._source_note_tag = dpg.add_text("", parent=self._camera_settings_group)
            self._mode_tag = dpg.add_combo(
                label="Capture mode",
                items=[],
                default_value="",
                width=-1,
                callback=self._on_mode_selected,
                parent=self._camera_settings_group,
            )
            self._request_60_fps_tag = dpg.add_checkbox(
                label="Request 60 FPS",
                callback=self._on_request_60_fps_changed,
                parent=self._camera_settings_group,
            )
            dpg.add_text("Camera preview", parent=self._camera_settings_group)
            dpg.add_texture_registry(
                tag="divergence-splitter-camera-preview-textures",
            )
            self._preview_group_tag = dpg.add_group(
                tag="divergence-splitter-camera-preview",
                width=480,
                height=270,
                parent=self._camera_settings_group,
            )
            self._preview_status_tag = dpg.add_text(
                "", parent=self._camera_settings_group
            )
            self._opened_camera_tag = dpg.add_text(
                "Opened camera: —", parent=self._camera_settings_group
            )
            self._video_settings_group = dpg.add_group()
            self._video_path_tag = dpg.add_input_text(
                label="Video file",
                width=-1,
                callback=self._on_video_path_changed,
                parent=self._video_settings_group,
            )
            dpg.add_button(
                label="Browse...",
                callback=self._on_browse_video,
                parent=self._video_settings_group,
            )
            dpg.configure_item(self._video_settings_group, show=False)

            dpg.add_separator()
            self._frame_processing_group = dpg.add_group()
            dpg.add_text("Frame processing", parent=self._frame_processing_group)
            self._crop_enabled_tag = dpg.add_checkbox(
                label="Crop",
                callback=self._on_crop_enabled_changed,
                parent=self._frame_processing_group,
            )
            self._crop_left_tag = dpg.add_input_int(
                label="Left",
                default_value=0,
                callback=self._on_crop_changed,
                parent=self._frame_processing_group,
            )
            self._crop_right_tag = dpg.add_input_int(
                label="Right",
                default_value=0,
                callback=self._on_crop_changed,
                parent=self._frame_processing_group,
            )
            self._crop_top_tag = dpg.add_input_int(
                label="Top",
                default_value=0,
                callback=self._on_crop_changed,
                parent=self._frame_processing_group,
            )
            self._crop_bottom_tag = dpg.add_input_int(
                label="Bottom",
                default_value=0,
                callback=self._on_crop_changed,
                parent=self._frame_processing_group,
            )
            self._resize_enabled_tag = dpg.add_checkbox(
                label="Resize",
                callback=self._on_resize_enabled_changed,
                parent=self._frame_processing_group,
            )
            self._resize_width_tag = dpg.add_input_int(
                label="Width",
                default_value=640,
                callback=self._on_resize_changed,
                parent=self._frame_processing_group,
            )
            self._resize_height_tag = dpg.add_input_int(
                label="Height",
                default_value=360,
                callback=self._on_resize_changed,
                parent=self._frame_processing_group,
            )

            dpg.add_separator()
            dpg.add_text("Instances")
            self._instances_group_tag = dpg.add_group()
            self._add_instance_tag = dpg.add_button(
                label="Add instance",
                callback=self._on_add_instance,
            )

            dpg.add_separator()
            self._log_level_tag = dpg.add_combo(
                label="Log level",
                items=list(LOG_LEVELS),
                default_value="INFO",
                callback=self._on_log_level_changed,
            )

            dpg.add_separator()
            self._status_tag = dpg.add_text("", color=(255, 200, 120))

        self._refresh_cameras(None, None)

    def open_configuration(self, path: Path) -> None:
        """Load and start one configuration, reporting errors in the screen."""

        try:
            configuration = load_configuration(path)
        except (ConfigurationFileError, ConfigurationValidationError) as error:
            self._set_status(_configuration_error_message(error))
            return
        draft = self._model.open_configuration(configuration, path)
        self._populate(draft)
        self._reload(path)

    def _start(self, path: Path) -> None:
        try:
            self._controller.start(path)
        except SessionAlreadyActiveError:
            self._set_status("a session is already running")
            return
        self._set_status(f"started {path.name}")

    def tick(self, state: SessionState) -> None:
        if self._pending_reload_path is not None and not is_active(state):
            path = self._pending_reload_path
            self._pending_reload_path = None
            self._start(path)
            state = self._controller.state
        if is_active(state):
            self._camera_preview.stop()
        else:
            frame = self._camera_preview.take_latest()
            if frame is not None:
                dpg.set_value(self._preview_status_tag, "")
                self._apply_preview_frame(frame)
            if self._camera_preview.error is not None:
                dpg.set_value(
                    self._preview_status_tag,
                    f"camera preview: {self._camera_preview.error}",
                )
        settings = self._camera_preview.capture_settings
        if settings is None:
            dpg.set_value(self._opened_camera_tag, "Opened camera: —")
        else:
            dpg.set_value(
                self._opened_camera_tag,
                f"Opened camera: {settings.width}×{settings.height} @ "
                f"{settings.fps:.2f} FPS",
            )
        permission = edit_permission(state)
        draft = self._model.draft
        instances_enabled = permission.instances and draft is not None
        source_enabled = permission.source and draft is not None
        if draft is not None:
            path_text = str(draft.configuration_path)
            if self._model.is_dirty:
                path_text += " *"
            self._sync_input(self._config_path_tag, path_text)
        dpg.configure_item(self._config_path_tag, enabled=False)
        dpg.configure_item(self._new_button_tag, enabled=permission.instances)
        dpg.configure_item(self._open_button_tag, enabled=permission.instances)
        dpg.configure_item(
            self._save_button_tag,
            enabled=draft is not None and permission.instances,
        )
        dpg.configure_item(self._save_as_button_tag, enabled=permission.instances)
        dpg.configure_item(self._add_instance_tag, enabled=instances_enabled)
        for index, row in self._instance_rows.items():
            editable = instances_enabled and index < len(draft.instances)
            dpg.configure_item(row.rpc_tag, enabled=editable)
            dpg.configure_item(row.event_tag, enabled=editable)
            dpg.configure_item(row.scenario_tag, enabled=editable)
            dpg.configure_item(row.browse_tag, enabled=editable)
            dpg.configure_item(row.remove_tag, enabled=editable)
        dpg.configure_item(self._camera_tag, enabled=source_enabled)
        dpg.configure_item(self._mode_tag, enabled=source_enabled)
        dpg.configure_item(self._request_60_fps_tag, enabled=source_enabled)
        transform = draft.source.transform if draft is not None else None
        crop = transform.crop if transform is not None else None
        resize = transform.resize if transform is not None else None
        dpg.configure_item(self._crop_enabled_tag, enabled=source_enabled)
        dpg.configure_item(self._resize_enabled_tag, enabled=source_enabled)
        for tag in (
            self._crop_left_tag,
            self._crop_right_tag,
            self._crop_top_tag,
            self._crop_bottom_tag,
        ):
            dpg.configure_item(tag, enabled=source_enabled and crop is not None)
        for tag in (self._resize_width_tag, self._resize_height_tag):
            dpg.configure_item(tag, enabled=source_enabled and resize is not None)
        if transform is not None:
            dpg.set_value(self._crop_enabled_tag, crop is not None)
            dpg.set_value(self._resize_enabled_tag, resize is not None)
            if crop is not None:
                dpg.set_value(self._crop_left_tag, crop.left)
                dpg.set_value(self._crop_right_tag, crop.right)
                dpg.set_value(self._crop_top_tag, crop.top)
                dpg.set_value(self._crop_bottom_tag, crop.bottom)
            if resize is not None:
                dpg.set_value(self._resize_width_tag, resize.width)
                dpg.set_value(self._resize_height_tag, resize.height)
        dpg.configure_item(
            self._log_level_tag,
            enabled=draft is not None and permission.log_level,
        )
        if draft is not None:
            for index, row in self._instance_rows.items():
                if index >= len(draft.instances):
                    continue
                instance = draft.instances[index]
                self._sync_input(row.rpc_tag, instance.rpc_endpoint)
                self._sync_input(row.event_tag, instance.event_endpoint)
                self._sync_input(row.scenario_tag, instance.scenario)

    def _sync_input(self, tag: int | str, value: str) -> None:
        if dpg.get_value(tag) != value:
            dpg.set_value(tag, value)

    def _populate(self, draft: EditableApplicationConfiguration) -> bool:
        path_text = str(draft.configuration_path)
        if self._model.is_dirty:
            path_text += " *"
        dpg.set_value(self._config_path_tag, path_text)
        self._rebuild_instance_editors(draft)
        dpg.set_value(self._log_level_tag, draft.log_level)
        dpg.set_value(
            self._source_type_tag, SOURCE_TYPE_LABELS[draft.source.selected_type]
        )
        dpg.set_value(self._video_path_tag, draft.source.video.path)
        transform = draft.source.transform
        crop = transform.crop
        resize = transform.resize
        dpg.set_value(self._crop_enabled_tag, crop is not None)
        dpg.set_value(self._crop_left_tag, crop.left if crop is not None else 0)
        dpg.set_value(self._crop_right_tag, crop.right if crop is not None else 0)
        dpg.set_value(self._crop_top_tag, crop.top if crop is not None else 0)
        dpg.set_value(self._crop_bottom_tag, crop.bottom if crop is not None else 0)
        dpg.set_value(self._resize_enabled_tag, resize is not None)
        dpg.set_value(
            self._resize_width_tag, resize.width if resize is not None else 640
        )
        dpg.set_value(
            self._resize_height_tag, resize.height if resize is not None else 360
        )
        self._show_source_settings(draft.source.selected_type)
        camera = camera_source(draft)
        if camera is None:
            self._camera_preview.stop()
            return True
        dpg.set_value(self._source_note_tag, "")
        dpg.set_value(self._request_60_fps_tag, camera.request_60_fps)
        return self._refresh_cameras(camera.device, camera.mode)

    def _rebuild_instance_editors(
        self, draft: EditableApplicationConfiguration
    ) -> None:
        dpg.delete_item(self._instances_group_tag, children_only=True)
        self._instance_rows = {}
        for index, instance in enumerate(draft.instances):
            self._instance_rows[index] = self._build_instance_editor(index, instance)

    def _build_instance_editor(
        self, index: int, instance: InstanceDraft
    ) -> _InstanceRow:
        parent = self._instances_group_tag
        number = index + 1
        dpg.add_text(f"Instance {number}", parent=parent)
        dpg.add_text("RPC endpoint", parent=parent)
        rpc_tag = dpg.add_input_text(
            parent=parent,
            default_value=instance.rpc_endpoint,
            width=-1,
            callback=self._on_instance_rpc_changed,
            user_data=index,
        )
        dpg.add_text("Event endpoint", parent=parent)
        event_tag = dpg.add_input_text(
            parent=parent,
            default_value=instance.event_endpoint,
            width=-1,
            callback=self._on_instance_event_changed,
            user_data=index,
        )
        dpg.add_text("Scenario", parent=parent)
        with dpg.group(horizontal=True, parent=parent):
            browse_tag = dpg.add_button(
                label="Browse...",
                callback=self._on_browse_instance_scenario,
                user_data=index,
            )
            scenario_tag = dpg.add_input_text(
                default_value=instance.scenario,
                width=-1,
                callback=self._on_instance_scenario_changed,
                user_data=index,
            )
        remove_tag = dpg.add_button(
            parent=parent,
            label="Remove",
            callback=self._on_remove_instance,
            user_data=index,
        )
        dpg.add_separator(parent=parent)
        return _InstanceRow(
            rpc_tag=rpc_tag,
            event_tag=event_tag,
            scenario_tag=scenario_tag,
            browse_tag=browse_tag,
            remove_tag=remove_tag,
        )

    def _refresh_cameras(
        self,
        configured: CameraDeviceConfiguration | None,
        configured_mode: CameraModeConfiguration | None,
    ) -> bool:
        self._camera_by_label = {}
        try:
            devices = tuple(self._model.list_cameras())
        except Exception as error:  # noqa: BLE001
            self._set_status(f"could not enumerate cameras: {error}")
            dpg.configure_item(self._camera_tag, items=[], default_value="")
            return False
        labels = []
        for device in devices:
            backend = _backend_value(device.backend)
            label = _CAMERA_LABEL_TEMPLATE.format(
                backend=_backend_display(backend), name=device.name, index=device.index
            )
            self._camera_by_label[label] = device
            labels.append(label)
        selected_device = (
            select_configured_camera(configured, devices)
            if configured is not None
            else None
        )
        if selected_device is None:
            selected = ""
            if configured is not None:
                self._set_status("configured camera is unavailable; select it again")
            dpg.configure_item(self._mode_tag, items=[], default_value="")
            resolved = False
        else:
            assert selected_device is not None
            selected = _CAMERA_LABEL_TEMPLATE.format(
                backend=_backend_display(_backend_value(selected_device.backend)),
                name=selected_device.name,
                index=selected_device.index,
            )
            resolved = True
            resolved = (
                self._refresh_modes(selected_device, configured_mode) and resolved
            )
        dpg.configure_item(self._camera_tag, items=labels, default_value=selected)
        return resolved

    def _refresh_modes(
        self, device: CameraDevice, configured_mode: CameraModeConfiguration | None
    ) -> bool:
        self._mode_by_label = {}
        labels = []
        for mode in device.modes:
            label = _mode_label(mode)
            self._mode_by_label[label] = mode
            labels.append(label)
        selected = ""
        if configured_mode is not None:
            try:
                mode = resolve_camera_mode(configured_mode, device.modes)
            except SourceConfigurationError:
                self._set_status(
                    "configured capture mode is unavailable; select it again"
                )
                dpg.configure_item(self._mode_tag, items=labels, default_value="")
                return False
            selected = _mode_label(mode)
        dpg.configure_item(self._mode_tag, items=labels, default_value=selected)
        if selected:
            assert configured_mode is not None
            self._start_camera_preview(
                selected_device=device,
                mode=mode,
            )
        else:
            self._camera_preview.stop()
        return True

    def _start_camera_preview(
        self, *, selected_device: CameraDevice, mode: CameraMode
    ) -> None:
        draft = self._model.draft
        if draft is None:
            return
        if is_active(self._controller.state):
            self._camera_preview.stop()
            return
        dpg.set_value(self._preview_status_tag, "opening camera preview...")
        camera = camera_source(draft)
        try:
            transform = draft.source.transform
            configuration = CameraSourceConfiguration(
                CameraDeviceConfiguration(
                    _camera_backend(selected_device.backend),
                    selected_device.name,
                    selected_device.index,
                ),
                CameraModeConfiguration(
                    mode.width,
                    mode.height,
                    mode.fps,
                    mode.subtype_guid,
                ),
                camera.request_60_fps if camera is not None else False,
                SourceTransformConfiguration(
                    None
                    if transform.crop is None
                    else CropConfiguration(
                        transform.crop.left,
                        transform.crop.right,
                        transform.crop.top,
                        transform.crop.bottom,
                    ),
                    None
                    if transform.resize is None
                    else ResizeConfiguration(
                        transform.resize.width, transform.resize.height
                    ),
                ),
            )
            self._camera_preview.start(configuration, draft.configuration_path.parent)
            dpg.set_value(self._preview_status_tag, "")
        except Exception as error:  # noqa: BLE001
            dpg.set_value(self._preview_status_tag, f"camera preview: {error}")

    def _apply_preview_frame(self, frame) -> None:
        rgba = to_rgba_float32(frame.image)
        signature = source_signature(frame.image)
        event = plan_texture(self._preview_signature, signature)
        if event is TextureEvent.UPDATE and self._preview_texture_tag is not None:
            dpg.set_value(self._preview_texture_tag, flatten(rgba))
            return
        if self._preview_image_tag is not None:
            dpg.delete_item(self._preview_image_tag)
        if self._preview_texture_tag is not None:
            dpg.delete_item(self._preview_texture_tag)
        self._preview_texture_tag = dpg.add_dynamic_texture(
            signature.width,
            signature.height,
            cast("list[float]", flatten(rgba)),
            parent="divergence-splitter-camera-preview-textures",
        )
        display_size = fit_preview(signature.width, signature.height, 480, 270)
        self._preview_image_tag = dpg.add_image(
            self._preview_texture_tag,
            parent=self._preview_group_tag,
            width=display_size.width,
            height=display_size.height,
        )
        self._preview_signature = signature

    def _on_browse_instance_scenario(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        index = int(user_data)
        path = select_open_script_file()
        if path is None:
            return
        path_text = str(path)
        if self._model.set_instance_scenario(index, path_text) is None:
            return
        row = self._instance_rows.get(index)
        if row is not None:
            dpg.set_value(row.scenario_tag, path_text)

    def _on_instance_rpc_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        self._model.set_instance_rpc_endpoint(user_data, app_data)

    def _on_instance_event_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        self._model.set_instance_event_endpoint(user_data, app_data)

    def _on_instance_scenario_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        self._model.set_instance_scenario(user_data, app_data)

    def _on_add_instance(self) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        draft = self._model.add_instance()
        if draft is not None:
            self._rebuild_instance_editors(draft)

    def _on_remove_instance(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        draft = self._model.remove_instance(user_data)
        if draft is not None:
            self._rebuild_instance_editors(draft)

    def _on_camera_selected(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        device = self._camera_by_label.get(app_data)
        if device is None:
            return
        self._model.set_camera_device(
            _camera_backend(device.backend), device.name, device.index
        )
        self._refresh_modes(device, None)

    def _show_source_settings(self, source_type: SourceType) -> None:
        camera = source_type is SourceType.CAMERA
        dpg.configure_item(self._camera_settings_group, show=camera)
        dpg.configure_item(self._video_settings_group, show=not camera)
        if not camera:
            self._camera_preview.stop()

    def _on_source_type_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        source_type = SOURCE_TYPE_BY_LABEL.get(app_data)
        if (
            source_type is not None
            and self._model.set_source_type(source_type) is not None
        ):
            self._show_source_settings(source_type)

    def _on_video_path_changed(self, sender, app_data, user_data) -> None:
        if edit_permission(self._controller.state).source:
            self._model.set_video_path(app_data)

    def _on_browse_video(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        path = select_open_file(title="Select video file", filters=VIDEO_FILTERS)
        if path is not None:
            value = str(path)
            dpg.set_value(self._video_path_tag, value)
            self._model.set_video_path(value)

    def _on_crop_enabled_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        if app_data:
            self._model.set_crop_values(
                int(dpg.get_value(self._crop_left_tag)),
                int(dpg.get_value(self._crop_right_tag)),
                int(dpg.get_value(self._crop_top_tag)),
                int(dpg.get_value(self._crop_bottom_tag)),
            )
        else:
            self._model.set_crop(None)
        self._update_camera_preview_transform()

    def _on_crop_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        if (
            self._model.draft is not None
            and self._model.draft.source.transform.crop is not None
        ):
            self._model.set_crop_values(
                int(dpg.get_value(self._crop_left_tag)),
                int(dpg.get_value(self._crop_right_tag)),
                int(dpg.get_value(self._crop_top_tag)),
                int(dpg.get_value(self._crop_bottom_tag)),
            )
            self._update_camera_preview_transform()

    def _on_resize_enabled_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        if app_data:
            self._model.set_resize_values(
                int(dpg.get_value(self._resize_width_tag)),
                int(dpg.get_value(self._resize_height_tag)),
            )
        else:
            self._model.set_resize(None)
        self._update_camera_preview_transform()

    def _on_resize_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        if (
            self._model.draft is not None
            and self._model.draft.source.transform.resize is not None
        ):
            self._model.set_resize_values(
                int(dpg.get_value(self._resize_width_tag)),
                int(dpg.get_value(self._resize_height_tag)),
            )
            self._update_camera_preview_transform()

    def _update_camera_preview_transform(self) -> None:
        draft = self._model.draft
        if draft is None:
            return
        transform = draft.source.transform
        try:
            self._camera_preview.update_transform(
                SourceTransformConfiguration(
                    None
                    if transform.crop is None
                    else CropConfiguration(
                        transform.crop.left,
                        transform.crop.right,
                        transform.crop.top,
                        transform.crop.bottom,
                    ),
                    None
                    if transform.resize is None
                    else ResizeConfiguration(
                        transform.resize.width, transform.resize.height
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            dpg.set_value(self._preview_status_tag, str(error))

    def _on_mode_selected(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        mode = self._mode_by_label.get(app_data)
        if mode is None:
            return
        self._model.set_camera_mode(
            CameraModeConfiguration(
                mode.width, mode.height, mode.fps, mode.subtype_guid
            )
        )
        self._start_camera_preview(selected_device=self._selected_camera(), mode=mode)

    def _on_request_60_fps_changed(self, sender, app_data, user_data) -> None:
        if not edit_permission(self._controller.state).source:
            return
        draft = self._model.set_request_60_fps(bool(app_data))
        if draft is None:
            return
        camera = camera_source(draft)
        if camera is None or camera.mode is None:
            self._camera_preview.stop()
            return
        self._refresh_modes(self._selected_camera(), camera.mode)

    def _selected_camera(self) -> CameraDevice:
        device = self._camera_by_label.get(str(dpg.get_value(self._camera_tag)))
        if device is None:
            raise ValueError("select a camera before selecting a capture mode")
        return device

    def _on_log_level_changed(self, sender, app_data, user_data) -> None:
        self._model.set_log_level(app_data)

    def close(self) -> None:
        self._camera_preview.stop()
        self._preview_image_tag = None
        self._preview_texture_tag = None
        self._preview_signature = None

    def _on_open(self) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        if not self._confirm_discard():
            return
        path = select_open_file(
            title="Open configuration", filters=CONFIGURATION_FILTERS
        )
        if path is not None:
            self.open_configuration(path)

    def _on_new(self) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        if not self._confirm_discard():
            return
        path = select_save_file(
            title="New configuration",
            filters=CONFIGURATION_FILTERS,
        )
        if path is None:
            return
        draft = self._model.create_default_configuration(path)
        try:
            devices = tuple(self._model.list_cameras())
        except Exception:  # noqa: BLE001
            devices = ()
        if devices:
            device = devices[0]
            mode = device.modes[0] if device.modes else None
            draft.source.camera.device = CameraDeviceConfiguration(
                _camera_backend(device.backend), device.name, device.index
            )
            draft.source.camera.mode = (
                CameraModeConfiguration(
                    mode.width, mode.height, mode.fps, mode.subtype_guid
                )
                if mode is not None
                else None
            )
        self._populate(draft)
        self._set_status("new configuration; save to apply it")

    def _on_save(self) -> None:
        if not edit_permission(self._controller.state).instances:
            return
        draft = self._model.draft
        if draft is None:
            self._set_status("open a configuration file first")
            return
        try:
            configuration = self._model.configuration()
        except ValueError as error:
            self._set_status(str(error))
            return
        if configuration is None:
            return
        try:
            save_configuration(draft.configuration_path, configuration)
        except OSError as error:
            self._set_status(f"could not save: {error}")
            return
        self._model.mark_saved()
        self._reload(draft.configuration_path)

    def _on_save_as(self) -> None:
        draft = self._model.draft
        if draft is None or not edit_permission(self._controller.state).instances:
            return
        path = select_save_file(
            title="Save configuration as",
            filters=CONFIGURATION_FILTERS,
            initial_path=draft.configuration_path,
        )
        if path is None:
            return
        try:
            configuration = self._model.configuration()
        except ValueError as error:
            self._set_status(str(error))
            return
        if configuration is None:
            return
        try:
            save_configuration(path, configuration)
        except OSError as error:
            self._set_status(f"could not save: {error}")
            return
        saved = self._model.mark_saved(path)
        assert saved is not None
        self._populate(saved)
        self._reload(path)

    def _reload(self, path: Path) -> None:
        if is_active(self._controller.state):
            self._pending_reload_path = path
            self._controller.request_stop()
            self._set_status("Reloading configuration...")
            return
        self._start(path)

    def _confirm_discard(self) -> bool:
        if not self._model.is_dirty:
            return True
        from divergencesplitter_ui.windows_file_dialog import confirm_discard

        return confirm_discard()

    def _set_status(self, message: str) -> None:
        dpg.set_value(self._status_tag, message)


def _configuration_error_message(
    error: ConfigurationFileError | ConfigurationValidationError,
) -> str:
    if isinstance(error, ConfigurationFileError):
        return f"could not read configuration: {error.error}"
    return f"invalid configuration: {error}"


def _backend_value(backend: object) -> str:
    value = getattr(backend, "value", None)
    if isinstance(value, str):
        return value
    return str(getattr(backend, "name", "")).lower()


def _camera_backend(backend: object) -> CameraBackend:
    return CameraBackend(_backend_value(backend))


def _backend_display(backend: str) -> str:
    return {
        "direct_show": "DirectShow",
        "media_foundation": "Media Foundation",
    }.get(backend, backend)


def _mode_label(mode: CameraMode) -> str:
    format_value = getattr(mode, "format", None) or getattr(mode, "subtype_guid", "")
    return f"{mode.width} × {mode.height} @ {mode.fps:g} fps — {format_value}"
