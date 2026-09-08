"""Dear PyGui settings screen for editing one configuration.

This module imports Dear PyGui and owns every settings widget. It edits the
single ``SettingsModel`` draft shared with the main screen and delegates load,
save, and start to the existing runtime configuration loader, saver, and the
``SessionController``. It never forks a second settings state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    resolve_camera_mode,
)

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionState,
    is_active,
)
from divergencesplitter_ui.settings import (
    LOG_LEVELS,
    CameraDevice,
    CameraMode,
    InstanceDraft,
    SettingsDraft,
    SettingsModel,
    camera_source,
    edit_permission,
    save_decision,
    select_configured_camera,
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


class SettingsWindow:
    """Own the settings widgets and drive open/save/start through the draft."""

    WINDOW_TAG = "divergence-splitter-settings"

    def __init__(self, controller: SessionController, model: SettingsModel) -> None:
        self._controller = controller
        self._model = model
        self._camera_by_label: dict[str, CameraDevice] = {}
        self._mode_by_label: dict[str, CameraMode] = {}
        self._instance_rows: dict[int, _InstanceRow] = {}
        self._pending_instance_index: int | None = None

    def build_main_shortcut(self, parent: int | str) -> None:
        """Add the main-screen shortcut into the settings screen."""

        dpg.add_button(
            parent=parent,
            label="Settings...",
            callback=self._on_show_settings,
        )

    def build(self) -> None:
        with dpg.window(
            tag=self.WINDOW_TAG,
            label="Settings",
            width=520,
            height=600,
            show=True,
        ):
            dpg.add_text("Configuration file")
            self._config_path_tag = dpg.add_input_text(
                default_value="",
                width=-1,
            )
            with dpg.group(horizontal=True):
                self._config_browse_tag = dpg.add_button(
                    label="Browse...",
                    callback=self._on_browse_config,
                )
                self._open_button_tag = dpg.add_button(
                    label="Open",
                    callback=self._on_open,
                )

            dpg.add_separator()
            dpg.add_text("Instances")
            self._instances_group_tag = dpg.add_group()
            self._add_instance_tag = dpg.add_button(
                label="Add instance",
                callback=self._on_add_instance,
            )

            dpg.add_separator()
            dpg.add_text("Camera")
            self._camera_tag = dpg.add_combo(
                items=[],
                default_value="",
                width=-1,
                callback=self._on_camera_selected,
            )
            self._source_note_tag = dpg.add_text("")
            self._mode_tag = dpg.add_combo(
                label="Capture mode",
                items=[],
                default_value="",
                width=-1,
                callback=self._on_mode_selected,
            )

            dpg.add_separator()
            self._log_level_tag = dpg.add_combo(
                label="Log level",
                items=list(LOG_LEVELS),
                default_value="INFO",
                callback=self._on_log_level_changed,
            )

            dpg.add_separator()
            self._save_button_tag = dpg.add_button(
                label="Save",
                callback=self._on_save,
            )
            self._status_tag = dpg.add_text("", color=(255, 200, 120))

        self._config_dialog_tag = dpg.add_file_dialog(
            label="Select configuration file",
            width=640,
            height=420,
            show=False,
            modal=True,
            callback=self._on_config_dialog,
            directory_selector=False,
            default_filename="config.json",
        )
        self._scenario_dialog_tag = dpg.add_file_dialog(
            label="Select scenario script",
            width=640,
            height=420,
            show=False,
            modal=True,
            callback=self._on_scenario_dialog,
            directory_selector=False,
        )
        dpg.add_file_extension(".py", parent=self._scenario_dialog_tag)
        dpg.add_file_extension(".yaml", parent=self._scenario_dialog_tag)
        dpg.add_file_extension(".yml", parent=self._scenario_dialog_tag)
        dpg.add_file_extension(".*", parent=self._scenario_dialog_tag)

    def open_configuration(self, path: Path) -> None:
        """Load and start one configuration, reporting errors in the screen."""

        if is_active(self._controller.state):
            self._set_status("stop the current session before opening a configuration")
            return
        try:
            configuration = load_configuration(path)
        except (ConfigurationFileError, ConfigurationValidationError) as error:
            self._set_status(_configuration_error_message(error))
            return
        draft = self._model.open_configuration(configuration, path)
        if self._populate(draft):
            self._start(path)

    def _start(self, path: Path) -> None:
        try:
            self._controller.start(path)
        except SessionAlreadyActiveError:
            self._set_status("a session is already running")
            return
        self._set_status(f"started {path.name}")

    def tick(self, state: SessionState) -> None:
        permission = edit_permission(active=is_active(state))
        draft = self._model.draft
        instances_enabled = permission.instances and draft is not None
        source_enabled = (
            permission.source and draft is not None and camera_source(draft) is not None
        )
        dpg.configure_item(self._config_path_tag, enabled=permission.instances)
        dpg.configure_item(self._config_browse_tag, enabled=permission.instances)
        dpg.configure_item(self._open_button_tag, enabled=permission.instances)
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
        dpg.configure_item(self._log_level_tag, enabled=draft is not None)
        dpg.configure_item(self._save_button_tag, enabled=draft is not None)
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

    def _populate(self, draft: SettingsDraft) -> bool:
        dpg.set_value(self._config_path_tag, str(draft.configuration_path))
        self._rebuild_instance_editors(draft)
        dpg.set_value(self._log_level_tag, draft.log_level)
        camera = camera_source(draft)
        if camera is None:
            self._camera_by_label = {}
            dpg.configure_item(self._camera_tag, items=[], default_value="")
            dpg.set_value(self._source_note_tag, "source type is not camera")
            dpg.configure_item(self._mode_tag, items=[], default_value="")
            return True
        dpg.set_value(self._source_note_tag, "")
        return self._refresh_cameras(camera.device, camera.mode)

    def _rebuild_instance_editors(self, draft: SettingsDraft) -> None:
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
            scenario_tag = dpg.add_input_text(
                default_value=instance.scenario,
                width=-1,
                callback=self._on_instance_scenario_changed,
                user_data=index,
            )
            browse_tag = dpg.add_button(
                label="Browse...",
                callback=self._on_browse_instance_scenario,
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
        configured: CameraDeviceConfiguration,
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
        selected_device = select_configured_camera(configured, devices)
        if selected_device is None:
            selected = ""
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
            self._model.set_camera_device(
                configured.backend, selected_device.name, selected_device.index
            )
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
            self._model.set_camera_mode(configured_mode)
        return True

    def _on_browse_config(self) -> None:
        if is_active(self._controller.state):
            return
        dpg.show_item(self._config_dialog_tag)

    def _on_show_settings(self) -> None:
        dpg.show_item(self.WINDOW_TAG)

    def _on_browse_instance_scenario(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        self._pending_instance_index = user_data
        dpg.show_item(self._scenario_dialog_tag)

    def _on_config_dialog(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        path = _dialog_path(app_data)
        if path is None:
            return
        dpg.set_value(self._config_path_tag, path)
        self.open_configuration(Path(path))

    def _on_scenario_dialog(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        index = self._pending_instance_index
        self._pending_instance_index = None
        if index is None:
            return
        path = _dialog_path(app_data)
        if path is None:
            return
        if self._model.set_instance_scenario(index, path) is None:
            return
        row = self._instance_rows.get(index)
        if row is not None:
            dpg.set_value(row.scenario_tag, path)

    def _on_instance_rpc_changed(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        self._model.set_instance_rpc_endpoint(user_data, app_data)

    def _on_instance_event_changed(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        self._model.set_instance_event_endpoint(user_data, app_data)

    def _on_instance_scenario_changed(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        self._model.set_instance_scenario(user_data, app_data)

    def _on_add_instance(self) -> None:
        if is_active(self._controller.state):
            return
        draft = self._model.add_instance()
        if draft is not None:
            self._rebuild_instance_editors(draft)

    def _on_remove_instance(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        draft = self._model.remove_instance(user_data)
        if draft is not None:
            self._rebuild_instance_editors(draft)

    def _on_camera_selected(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        device = self._camera_by_label.get(app_data)
        if device is None:
            return
        self._model.set_camera_device(
            _camera_backend(device.backend), device.name, device.index
        )
        self._refresh_modes(device, None)

    def _on_mode_selected(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        mode = self._mode_by_label.get(app_data)
        if mode is None:
            return
        self._model.set_camera_mode(
            CameraModeConfiguration(
                mode.width, mode.height, mode.fps, mode.subtype_guid
            )
        )

    def _on_log_level_changed(self, sender, app_data, user_data) -> None:
        self._model.set_log_level(app_data)

    def _on_open(self) -> None:
        path_text = str(dpg.get_value(self._config_path_tag)).strip()
        if not path_text:
            self._set_status("enter a configuration file path")
            return
        self.open_configuration(Path(path_text))

    def _on_save(self) -> None:
        draft = self._model.draft
        if draft is None:
            self._set_status("open a configuration file first")
            return
        active = is_active(self._controller.state)
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
        decision = save_decision(active=active)
        if decision.reflect_log_level and self._controller.diagnostics is not None:
            self._controller.set_log_level(configuration.runtime.log_level)
        if decision.start:
            self._start(draft.configuration_path)
        else:
            self._set_status("saved")

    def _set_status(self, message: str) -> None:
        dpg.set_value(self._status_tag, message)


def _dialog_path(app_data) -> str | None:
    if not app_data:
        return None
    value = app_data.get("file_path_name")
    if not value:
        return None
    return str(value)


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
