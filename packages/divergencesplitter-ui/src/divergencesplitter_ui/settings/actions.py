"""Application Settings operations for the Flet front end.

App Settings (theme, logging level, reaction time) are deliberately separate
from Profile files: they are written to the App Settings file, never mark the
Profile dirty, and never rewrite a Profile. Only the reaction time reloads a
running Profile, because the runtime reads it from App Settings at startup.
These operations are GUI-independent so the settings screen stays presentation.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from divergencesplitter_runtime.configuration.app_settings_json import (
    save_app_settings,
)
from divergencesplitter_runtime.configuration.models import Theme

from divergencesplitter_ui.session import SessionController
from divergencesplitter_ui.settings.model import SettingsModel


def persist_app_settings(model: SettingsModel, settings_path: Path) -> str | None:
    """Write the App Settings document; return an error message on failure."""

    try:
        save_app_settings(settings_path, model.app_settings_document())
    except OSError as error:
        return f"could not save app settings: {error}"
    return None


class AppSettingsActions:
    """Persist and apply App Settings without touching the Profile file."""

    def __init__(
        self,
        controller: SessionController,
        model: SettingsModel,
        *,
        settings_path: Path,
        on_theme_applied: Callable[[Theme], None] | None = None,
        on_reload: Callable[[Path], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self._controller = controller
        self._model = model
        self._settings_path = settings_path
        self._on_theme_applied = on_theme_applied
        self._on_reload = on_reload
        self._on_status = on_status
        self._status = ""
        self._settings_error: str | None = None

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, message: str) -> None:
        self._status = message
        if self._on_status is not None:
            self._on_status(message)

    def set_theme(self, theme: Theme) -> None:
        """Persist the theme to App Settings and apply it live.

        The theme lives in its own settings file, not in a Profile, so it is
        written immediately and never restarts the runtime.
        """

        self._model.set_theme(theme)
        self._persist()
        if self._on_theme_applied is not None:
            self._on_theme_applied(self._model.app_settings.theme)

    def set_log_level(self, level: str) -> None:
        """Persist the log level and apply it live; never restarts the runtime."""

        self._model.set_log_level(level)
        self._controller.set_log_level(level)
        self._persist()

    def set_reaction_time(self, value: int) -> None:
        """Persist a committed reaction time and reload the running Profile.

        Only a committed value reaches here, so typing a partial number in the
        field never restarts the runtime. The Profile file itself is not touched.
        """

        try:
            self._model.set_reaction_time_ms(value)
        except ValueError as error:
            self.set_status(str(error))
            return
        self._persist()
        draft = self._model.draft
        if draft is not None and self._on_reload is not None:
            self._on_reload(draft.profile_path)

    def _persist(self) -> bool:
        error = persist_app_settings(self._model, self._settings_path)
        if error is not None:
            self._settings_error = error
            self.set_status(error)
            return False
        self._settings_error = None
        return True
