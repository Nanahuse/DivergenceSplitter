"""Profile file operation orchestration for the Flet front end.

This module is GUI-independent: it drives the shared ``SettingsModel`` and the
existing ``SessionController`` through New/Open/Save/Save As and the save-time
reload, using the ``FileDialogs`` protocol for user choices. Application
Settings operations live in ``settings.actions.AppSettingsActions`` instead.
Editing a Profile draft never touches the running runtime; only a successful
save reloads it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraModeConfiguration,
)
from divergencesplitter_runtime.configuration.profile_json import (
    load_profile,
    save_profile,
)
from divergencesplitter_runtime.configuration.strict_json import (
    ConfigurationFileError,
    ConfigurationValidationError,
)

from divergencesplitter_ui.configuration.dialogs import (
    PROFILE_EXTENSIONS,
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
from divergencesplitter_ui.settings.actions import persist_app_settings


def profile_error_message(
    error: ConfigurationFileError | ConfigurationValidationError,
) -> str:
    if isinstance(error, ConfigurationFileError):
        return f"could not read profile: {error.error}"
    return f"invalid profile: {error}"


class ProfileActions:
    """Perform New/Open/Save/Save As and the save-time reload."""

    def __init__(
        self,
        controller: SessionController,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        settings_path: Path,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self._controller = controller
        self._model = model
        self._dialogs = dialogs
        self._settings_path = settings_path
        self._on_status = on_status
        self._status = ""
        self._settings_error: str | None = None
        self._pending_reload_path: Path | None = None

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, message: str) -> None:
        """Record a status and emit it as a notification event.

        Each call is a new event even when the message is unchanged, so a
        repeated Save always produces a fresh notification.
        """

        self._status = message
        if self._on_status is not None:
            self._on_status(message)

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
        """Ask for a save path, then start a fresh camera-first Profile draft."""

        if not self._can_edit(state):
            return False
        if not await self._confirm_discard():
            return False
        path = await self._dialogs.save_file(
            title="New Profile",
            extensions=PROFILE_EXTENSIONS,
            default_name="profile.json",
        )
        if path is None:
            return False
        draft = self._model.create_default_profile(path)
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
        # A new Profile is only a draft: last_profile is not updated until the
        # first successful write.
        self.set_status("new profile; save to apply it")
        return True

    async def open(self, state: SessionState) -> bool:
        """Pick and load a Profile, then start it."""

        if not self._can_edit(state):
            return False
        if not await self._confirm_discard():
            return False
        path = await self._dialogs.open_file(
            title="Open Profile",
            extensions=PROFILE_EXTENSIONS,
        )
        if path is None:
            return False
        try:
            profile = load_profile(path)
        except (ConfigurationFileError, ConfigurationValidationError) as error:
            # A bad file must not disturb the Profile already in use.
            self.set_status(profile_error_message(error))
            return False
        self._model.open_profile(profile, path)
        self.set_status(f"opened {path.name}")
        self._remember_last_profile(path)
        self.reload(path)
        return True

    async def save(self, state: SessionState) -> bool:
        """Save the draft to its current path, then reload."""

        if not self._can_edit(state):
            return False
        draft = self._model.draft
        if draft is None:
            self.set_status("open a profile file first")
            return False
        try:
            profile = self._model.profile_document()
        except ValueError as error:
            self.set_status(str(error))
            return False
        if profile is None:
            return False
        try:
            save_profile(draft.profile_path, profile)
        except OSError as error:
            # A failed save must leave the running session untouched.
            self.set_status(f"could not save: {error}")
            return False
        self._model.mark_saved()
        self.set_status(f"saved {draft.profile_path.name}")
        self._remember_last_profile(draft.profile_path)
        self.reload(draft.profile_path)
        return True

    async def save_as(self, state: SessionState) -> bool:
        """Save the draft to a new path, update it, then reload."""

        draft = self._model.draft
        if draft is None or not self._can_edit(state):
            return False
        path = await self._dialogs.save_file(
            title="Save Profile As",
            extensions=PROFILE_EXTENSIONS,
            initial_path=draft.profile_path,
        )
        if path is None:
            return False
        try:
            profile = self._model.profile_document()
        except ValueError as error:
            self.set_status(str(error))
            return False
        if profile is None:
            return False
        try:
            save_profile(path, profile)
        except OSError as error:
            self.set_status(f"could not save: {error}")
            return False
        self._model.mark_saved(path)
        self.set_status(f"saved {path.name}")
        self._remember_last_profile(path)
        self.reload(path)
        return True

    def _remember_last_profile(self, path: Path) -> None:
        # A successful Profile operation updates last_profile; if only the App
        # Settings write fails, the Profile operation itself is not rolled back.
        self._model.set_last_profile(path)
        self._persist_app_settings()

    def _persist_app_settings(self) -> bool:
        error = persist_app_settings(self._model, self._settings_path)
        if error is not None:
            self._settings_error = error
            self.set_status(error)
            return False
        self._settings_error = None
        return True

    def reload(self, path: Path) -> None:
        """Stop the running session before restarting it with ``path``."""

        self._pending_reload_path = path
        if is_active(self._controller.state):
            self._controller.request_stop()
            self.set_status("Reloading profile...")
            return
        self.advance(self._controller.state)

    def advance(self, state: SessionState) -> bool:
        """Start a pending reload once the previous session has stopped."""

        if self._pending_reload_path is not None and not is_active(state):
            path = self._pending_reload_path
            if self._start(path):
                self._pending_reload_path = None
                return True
        return False

    def _start(self, path: Path) -> bool:
        settings = replace(self._model.app_settings_document(), last_profile=None)
        try:
            self._controller.start(path, app_settings=settings)
        except SessionAlreadyActiveError:
            # A terminal state can be published before the session thread exits.
            # Keep the reload queued for the next tick without blocking the UI.
            return False
        message = f"started {path.name}"
        if self._settings_error is not None:
            message = f"{message} ({self._settings_error})"
        self.set_status(message)
        return True
