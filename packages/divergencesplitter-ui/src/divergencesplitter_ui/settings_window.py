"""Dear PyGui settings screen for editing one configuration.

This module imports Dear PyGui and owns every settings widget. It edits the
single ``SettingsModel`` draft shared with the main screen and delegates load,
save, and start to the existing runtime configuration loader, saver, and the
``SessionController``. It never forks a second settings state.
"""

from __future__ import annotations

from pathlib import Path

from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_configuration,
    save_configuration,
)
from divergencesplitter_runtime.configuration.models import CameraDeviceConfiguration

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionState,
    is_active,
)
from divergencesplitter_ui.settings import (
    LOG_LEVELS,
    SettingsDraft,
    SettingsModel,
    camera_source,
    edit_permission,
    parse_camera_dimensions,
    save_decision,
    select_configured_camera,
)

_CAMERA_LABEL_TEMPLATE = "{name} (id {id})"


class SettingsWindow:
    """Own the settings widgets and drive open/save/start through the draft."""

    WINDOW_TAG = "divergence-splitter-settings"

    def __init__(self, controller: SessionController, model: SettingsModel) -> None:
        self._controller = controller
        self._model = model
        self._main_scenario_tag: int | str | None = None
        self._main_scenario_browse_tag: int | str | None = None
        self._camera_by_label: dict[str, tuple[str, int]] = {}

    def build_main_shortcut(self, parent: int | str) -> None:
        """Add the main-screen shortcut backed by the shared scenario draft."""

        dpg.add_button(
            parent=parent,
            label="Settings...",
            callback=self._on_show_settings,
        )
        dpg.add_text("Scenario script", parent=parent)
        self._main_scenario_tag = dpg.add_input_text(
            parent=parent,
            default_value="",
            width=-1,
            callback=self._on_scenario_changed,
        )
        self._main_scenario_browse_tag = dpg.add_button(
            parent=parent,
            label="Browse scenario...",
            callback=self._on_browse_scenario,
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
            dpg.add_text("Scenario script")
            self._scenario_tag = dpg.add_input_text(
                default_value="",
                width=-1,
                callback=self._on_scenario_changed,
            )
            with dpg.group(horizontal=True):
                self._scenario_browse_tag = dpg.add_button(
                    label="Browse...",
                    callback=self._on_browse_scenario,
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
            self._width_tag = dpg.add_input_int(
                label="Width",
                default_value=0,
                callback=self._on_dimensions_changed,
            )
            self._height_tag = dpg.add_input_int(
                label="Height",
                default_value=0,
                callback=self._on_dimensions_changed,
            )
            self._fps_tag = dpg.add_input_float(
                label="FPS",
                default_value=0.0,
                format="%.2f",
                callback=self._on_dimensions_changed,
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
        scenario_enabled = permission.scenario and draft is not None
        source_enabled = (
            permission.source and draft is not None and camera_source(draft) is not None
        )
        dpg.configure_item(self._config_path_tag, enabled=permission.scenario)
        dpg.configure_item(self._config_browse_tag, enabled=permission.scenario)
        dpg.configure_item(self._open_button_tag, enabled=permission.scenario)
        dpg.configure_item(self._scenario_tag, enabled=scenario_enabled)
        dpg.configure_item(self._scenario_browse_tag, enabled=scenario_enabled)
        if self._main_scenario_tag is not None:
            dpg.configure_item(self._main_scenario_tag, enabled=scenario_enabled)
        if self._main_scenario_browse_tag is not None:
            dpg.configure_item(
                self._main_scenario_browse_tag,
                enabled=scenario_enabled,
            )
        dpg.configure_item(self._camera_tag, enabled=source_enabled)
        dpg.configure_item(self._width_tag, enabled=source_enabled)
        dpg.configure_item(self._height_tag, enabled=source_enabled)
        dpg.configure_item(self._fps_tag, enabled=source_enabled)
        dpg.configure_item(self._log_level_tag, enabled=draft is not None)
        dpg.configure_item(self._save_button_tag, enabled=draft is not None)
        if draft is not None:
            self._sync_input(self._scenario_tag, draft.scenario_script)
            if self._main_scenario_tag is not None:
                self._sync_input(self._main_scenario_tag, draft.scenario_script)

    def _sync_input(self, tag: int | str, value: str) -> None:
        if dpg.get_value(tag) != value:
            dpg.set_value(tag, value)

    def _populate(self, draft: SettingsDraft) -> bool:
        dpg.set_value(self._config_path_tag, str(draft.configuration_path))
        dpg.set_value(self._scenario_tag, draft.scenario_script)
        dpg.set_value(self._log_level_tag, draft.log_level)
        camera = camera_source(draft)
        if camera is None:
            self._camera_by_label = {}
            dpg.configure_item(self._camera_tag, items=[], default_value="")
            dpg.set_value(self._source_note_tag, "source type is not camera")
            dpg.set_value(self._width_tag, 0)
            dpg.set_value(self._height_tag, 0)
            dpg.set_value(self._fps_tag, 0.0)
            return True
        dpg.set_value(self._source_note_tag, "")
        dpg.set_value(self._width_tag, camera.width)
        dpg.set_value(self._height_tag, camera.height)
        dpg.set_value(self._fps_tag, camera.fps)
        return self._refresh_cameras(camera.device.name, camera.device.id)

    def _refresh_cameras(self, name: str, id: int) -> bool:
        self._camera_by_label = {}
        try:
            devices = tuple(self._model.list_cameras())
        except Exception as error:  # noqa: BLE001
            self._set_status(f"could not enumerate cameras: {error}")
            dpg.configure_item(self._camera_tag, items=[], default_value="")
            return False
        labels = []
        for device in devices:
            label = _CAMERA_LABEL_TEMPLATE.format(name=device.name, id=device.id)
            self._camera_by_label[label] = (device.name, device.id)
            labels.append(label)
        configured = CameraDeviceConfiguration(name, id)
        selected_device = select_configured_camera(configured, devices)
        if selected_device is None:
            selected = ""
            self._set_status("configured camera is unavailable; select it again")
            resolved = False
        else:
            selected = _CAMERA_LABEL_TEMPLATE.format(
                name=selected_device.name,
                id=selected_device.id,
            )
            self._model.set_camera_device(selected_device.name, selected_device.id)
            resolved = True
        dpg.configure_item(self._camera_tag, items=labels, default_value=selected)
        return resolved

    def _on_browse_config(self) -> None:
        if is_active(self._controller.state):
            return
        dpg.show_item(self._config_dialog_tag)

    def _on_show_settings(self) -> None:
        dpg.show_item(self.WINDOW_TAG)

    def _on_browse_scenario(self) -> None:
        if is_active(self._controller.state):
            return
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
        path = _dialog_path(app_data)
        if path is None:
            return
        self._model.set_scenario_script(path)
        dpg.set_value(self._scenario_tag, path)

    def _on_scenario_changed(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        self._model.set_scenario_script(app_data)

    def _on_camera_selected(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        device = self._camera_by_label.get(app_data)
        if device is None:
            return
        name, id = device
        self._model.set_camera_device(name, id)

    def _on_dimensions_changed(self, sender, app_data, user_data) -> None:
        if is_active(self._controller.state):
            return
        self._apply_dimensions()

    def _apply_dimensions(self) -> bool:
        draft = self._model.draft
        if draft is None or camera_source(draft) is None:
            return True
        try:
            dimensions = parse_camera_dimensions(
                str(dpg.get_value(self._width_tag)),
                str(dpg.get_value(self._height_tag)),
                str(dpg.get_value(self._fps_tag)),
            )
        except ValueError, TypeError:
            self._set_status("camera width, height, and fps must be numbers")
            return False
        try:
            self._model.set_camera_dimensions(
                dimensions.width,
                dimensions.height,
                dimensions.fps,
            )
        except ValueError as error:
            self._set_status(str(error))
            return False
        return True

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
        if not active and not self._apply_dimensions():
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
