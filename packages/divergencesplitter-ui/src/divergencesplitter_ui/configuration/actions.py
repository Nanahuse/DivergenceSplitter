"""File operation orchestration for the Flet Configuration page.

This module is GUI-independent: it drives the shared ``SettingsModel`` and the
existing ``SessionController`` through New/Open/Save/Save As, App Settings
persistence, and the save-time reload, using the ``FileDialogs`` protocol for
user choices. Editing a Profile draft never touches the running runtime; only a
successful save or a committed App Settings change reloads it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from divergencesplitter_runtime.configuration.app_settings_json import (
    save_app_settings,
)
from divergencesplitter_runtime.configuration.models import (
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    Theme,
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


def profile_error_message(
    error: ConfigurationFileError | ConfigurationValidationError,
) -> str:
    if isinstance(error, ConfigurationFileError):
        return f"could not read profile: {error.error}"
    return f"invalid profile: {error}"


class ProfileActions:
    """Perform New/Open/Save/Save As, App Settings persistence, and reloads."""

    def __init__(
        self,
        controller: SessionController,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        settings_path: Path,
        on_theme_applied: Callable[[Theme], None] | None = None,
    ) -> None:
        self._controller = controller
        self._model = model
        self._dialogs = dialogs
        self._settings_path = settings_path
        self._on_theme_applied = on_theme_applied
        self._status = ""
        self._settings_error: str | None = None
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
        self._status = "new profile; save to apply it"
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
            self._status = profile_error_message(error)
            return False
        self._model.open_profile(profile, path)
        self._status = f"opened {path.name}"
        self._remember_last_profile(path)
        self.reload(path)
        return True

    async def save(self, state: SessionState) -> bool:
        """Save the draft to its current path, then reload."""

        if not self._can_edit(state):
            return False
        draft = self._model.draft
        if draft is None:
            self._status = "open a profile file first"
            return False
        try:
            profile = self._model.profile_document()
        except ValueError as error:
            self._status = str(error)
            return False
        if profile is None:
            return False
        try:
            save_profile(draft.profile_path, profile)
        except OSError as error:
            # A failed save must leave the running session untouched.
            self._status = f"could not save: {error}"
            return False
        self._model.mark_saved()
        self._status = f"saved {draft.profile_path.name}"
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
            self._status = str(error)
            return False
        if profile is None:
            return False
        try:
            save_profile(path, profile)
        except OSError as error:
            self._status = f"could not save: {error}"
            return False
        self._model.mark_saved(path)
        self._status = f"saved {path.name}"
        self._remember_last_profile(path)
        self.reload(path)
        return True

    def set_log_level(self, level: str) -> None:
        """Persist the log level and apply it live; never restarts the runtime."""

        self._model.set_log_level(level)
        self._controller.set_log_level(level)
        self._persist_app_settings()

    def set_theme(self, theme: Theme) -> None:
        """Persist the theme to App Settings and apply it live.

        The theme lives in its own settings file, not in a Profile, so it is
        written immediately like the log level and never restarts the runtime.
        """

        self._model.set_theme(theme)
        self._persist_app_settings()
        if self._on_theme_applied is not None:
            self._on_theme_applied(self._model.app_settings.theme)

    def commit_reaction_time(self, value: int) -> None:
        """Persist a committed reaction time and reload the running Profile.

        Only a committed value reaches here, so typing a partial number in the
        field never restarts the runtime. The Profile file itself is not touched.
        """

        try:
            self._model.set_reaction_time_ms(value)
        except ValueError as error:
            self._status = str(error)
            return
        self._persist_app_settings()
        draft = self._model.draft
        if draft is not None:
            self.reload(draft.profile_path)

    def _remember_last_profile(self, path: Path) -> None:
        # A successful Profile operation updates last_profile; if only the App
        # Settings write fails, the Profile operation itself is not rolled back.
        self._model.set_last_profile(path)
        self._persist_app_settings()

    def _persist_app_settings(self) -> bool:
        try:
            save_app_settings(self._settings_path, self._model.app_settings_document())
        except OSError as error:
            self._settings_error = f"could not save app settings: {error}"
            self._status = self._settings_error
            return False
        self._settings_error = None
        return True

    def reload(self, path: Path) -> None:
        """Stop the running session before restarting it with ``path``."""

        if is_active(self._controller.state):
            self._pending_reload_path = path
            self._controller.request_stop()
            self._status = "Reloading profile..."
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
        settings = replace(self._model.app_settings_document(), last_profile=None)
        try:
            self._controller.start(path, app_settings=settings)
        except SessionAlreadyActiveError:
            self._status = "a session is already running"
            return
        message = f"started {path.name}"
        if self._settings_error is not None:
            message = f"{message} ({self._settings_error})"
        self._status = message
