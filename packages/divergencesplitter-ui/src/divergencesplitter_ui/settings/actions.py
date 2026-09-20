"""Application Settings operations for the Flet front end.

App Settings (theme, logging level, reaction time) are deliberately separate
from Profile files: they are written to the App Settings file, never mark the
Profile dirty, and never rewrite a Profile. Editing the settings screen only
updates a draft; :meth:`AppSettingsActions.apply` validates the whole draft,
persists it once, and only then reflects it: the theme is applied to the UI and
a running runtime is restarted exactly once with the new reaction time and log
level. These operations are GUI-independent so the settings screen stays
presentation.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from divergencesplitter_runtime.configuration.app_settings_json import (
    save_app_settings,
)
from divergencesplitter_runtime.configuration.models import AppSettings, Theme

from divergencesplitter_ui.session import SessionController, is_active
from divergencesplitter_ui.settings.model import SettingsModel


def save_app_settings_document(
    settings_path: Path, document: AppSettings
) -> str | None:
    """Write one App Settings document; return an error message on failure."""

    try:
        save_app_settings(settings_path, document)
    except OSError as error:
        return f"could not save app settings: {error}"
    return None


def persist_app_settings(model: SettingsModel, settings_path: Path) -> str | None:
    """Write the applied App Settings document; return an error on failure."""

    return save_app_settings_document(settings_path, model.app_settings_document())


class AppSettingsActions:
    """Persist and apply the App Settings draft without touching a Profile."""

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

    def apply(self) -> bool:
        """Validate, save, and reflect the App Settings draft in one step.

        Validation and persistence complete before anything is reflected, so a
        failure applies nothing: the applied settings, the theme, and the running
        runtime are all left untouched and the draft is kept for correction.
        """

        if not self._model.app_settings_dirty:
            # Nothing changed: never write or reflect anything.
            self.set_status("")
            return True

        try:
            settings = self._model.validate_app_settings()
        except ValueError as error:
            self.set_status(str(error))
            return False

        applied = self._model.applied_app_settings
        theme_changed = settings.theme is not applied.theme
        runtime_changed = (
            settings.log_level != applied.log_level
            or settings.reaction_time_ms != applied.reaction_time_ms
        )

        error = save_app_settings_document(
            self._settings_path, self._model.app_settings_document(settings)
        )
        if error is not None:
            self._settings_error = error
            self.set_status(error)
            return False
        self._settings_error = None

        # Only a successful save reaches here; commit the applied state first so
        # a queued runtime restart starts with the new reaction time and level.
        self._model.apply_app_settings(settings)
        if theme_changed and self._on_theme_applied is not None:
            self._on_theme_applied(settings.theme)
        if runtime_changed and self._on_reload is not None:
            draft = self._model.draft
            if draft is not None and is_active(self._controller.state):
                # A single reload covers both reaction time and log level. A
                # stopped runtime is never started by Apply; it picks the new
                # settings up on its next start.
                self._on_reload(draft.profile_path)
        self.set_status("")
        return True
