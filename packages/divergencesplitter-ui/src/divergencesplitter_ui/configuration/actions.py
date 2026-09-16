"""File operation orchestration for the Flet Configuration page.

This module is GUI-independent: it drives the shared ``SettingsModel`` and the
existing ``SessionController`` through New/Open/Save/Save As and the save-time
reload, using the ``FileDialogs`` protocol for user choices. The Flet page only
calls these actions and renders ``status``. Editing a draft never touches the
running runtime; only a successful save reloads it.
"""

from __future__ import annotations

from pathlib import Path

from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_configuration,
    save_configuration,
)
from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraModeConfiguration,
)

from divergencesplitter_ui.configuration.dialogs import (
    CONFIGURATION_EXTENSIONS,
    FileDialogs,
)
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionState,
    is_active,
)
from divergencesplitter_ui.settings import (
    SettingsModel,
    camera_backend,
    edit_permission,
)


def configuration_error_message(
    error: ConfigurationFileError | ConfigurationValidationError,
) -> str:
    if isinstance(error, ConfigurationFileError):
        return f"could not read configuration: {error.error}"
    return f"invalid configuration: {error}"


class ConfigurationActions:
    """Perform New/Open/Save/Save As and the save-time reload."""

    def __init__(
        self,
        controller: SessionController,
        model: SettingsModel,
        dialogs: FileDialogs,
    ) -> None:
        self._controller = controller
        self._model = model
        self._dialogs = dialogs
        self._status = ""
        self._pending_reload_path: Path | None = None

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, message: str) -> None:
        self._status = message

    def _can_edit(self, state: SessionState) -> bool:
        return edit_permission(state).instances

    async def _confirm_discard(self) -> bool:
        if not self._model.is_dirty:
            return True
        return await self._dialogs.confirm_discard()

    def _list_cameras(self):
        try:
            return tuple(self._model.list_cameras())
        except Exception:  # noqa: BLE001 - enumeration failure is an expected input
            return ()

    async def new(self, state: SessionState) -> bool:
        """Ask for a save path, then start a fresh camera-first draft."""

        if not self._can_edit(state):
            return False
        if not await self._confirm_discard():
            return False
        path = await self._dialogs.save_file(
            title="New configuration",
            extensions=CONFIGURATION_EXTENSIONS,
            default_name="configuration.json",
        )
        if path is None:
            return False
        draft = self._model.create_default_configuration(path)
        devices = self._list_cameras()
        if devices:
            device = devices[0]
            mode = device.modes[0] if device.modes else None
            draft.source.camera.device = CameraDeviceConfiguration(
                camera_backend(device.backend), device.name, device.index
            )
            draft.source.camera.mode = (
                None
                if mode is None
                else CameraModeConfiguration(
                    mode.width, mode.height, mode.fps, mode.subtype_guid
                )
            )
        self._status = "new configuration; save to apply it"
        return True

    async def open(self, state: SessionState) -> bool:
        """Pick and load a configuration, then start it."""

        if not self._can_edit(state):
            return False
        if not await self._confirm_discard():
            return False
        path = await self._dialogs.open_file(
            title="Open configuration",
            extensions=CONFIGURATION_EXTENSIONS,
        )
        if path is None:
            return False
        try:
            configuration = load_configuration(path)
        except (ConfigurationFileError, ConfigurationValidationError) as error:
            # A bad file must not disturb the configuration already in use.
            self._status = configuration_error_message(error)
            return False
        self._model.open_configuration(configuration, path)
        self._status = f"opened {path.name}"
        self.reload(path)
        return True

    async def save(self, state: SessionState) -> bool:
        """Save the draft to its current path, then reload."""

        if not self._can_edit(state):
            return False
        draft = self._model.draft
        if draft is None:
            self._status = "open a configuration file first"
            return False
        try:
            configuration = self._model.configuration()
        except ValueError as error:
            self._status = str(error)
            return False
        if configuration is None:
            return False
        try:
            save_configuration(draft.configuration_path, configuration)
        except OSError as error:
            # A failed save must leave the running session untouched.
            self._status = f"could not save: {error}"
            return False
        self._model.mark_saved()
        self._status = f"saved {draft.configuration_path.name}"
        self.reload(draft.configuration_path)
        return True

    async def save_as(self, state: SessionState) -> bool:
        """Save the draft to a new path, update it, then reload."""

        draft = self._model.draft
        if draft is None or not self._can_edit(state):
            return False
        path = await self._dialogs.save_file(
            title="Save configuration as",
            extensions=CONFIGURATION_EXTENSIONS,
            initial_path=draft.configuration_path,
        )
        if path is None:
            return False
        try:
            configuration = self._model.configuration()
        except ValueError as error:
            self._status = str(error)
            return False
        if configuration is None:
            return False
        try:
            save_configuration(path, configuration)
        except OSError as error:
            self._status = f"could not save: {error}"
            return False
        self._model.mark_saved(path)
        self._status = f"saved {path.name}"
        self.reload(path)
        return True

    def reload(self, path: Path) -> None:
        """Stop the running session before restarting it with ``path``."""

        if is_active(self._controller.state):
            self._pending_reload_path = path
            self._controller.request_stop()
            self._status = "Reloading configuration..."
            return
        self._start(path)

    def advance(self, state: SessionState) -> bool:
        """Start a pending reload once the previous session has stopped."""

        if self._pending_reload_path is not None and not is_active(state):
            path = self._pending_reload_path
            self._pending_reload_path = None
            self._start(path)
            return True
        return False

    def _start(self, path: Path) -> None:
        try:
            self._controller.start(path)
        except SessionAlreadyActiveError:
            self._status = "a session is already running"
            return
        self._status = f"started {path.name}"
