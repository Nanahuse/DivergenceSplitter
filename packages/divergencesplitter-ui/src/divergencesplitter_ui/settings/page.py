"""Application Settings screen for the Flet front end.

The screen edits App Settings only: the appearance theme, the reaction time, and
the logging level. It is presentation, delegating persistence and application to
``AppSettingsActions``. Theme, log level, and reaction time live in the App
Settings file rather than a Profile, so they never mark the Profile dirty and
the screen stays fully usable without a selected Profile.
"""

from __future__ import annotations

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme

from divergencesplitter_ui.settings.actions import AppSettingsActions
from divergencesplitter_ui.settings.model import (
    EditableAppSettings,
    EditPermission,
    SettingsModel,
)

_LOG_FILE_NOTE = "DEBUG log: see diagnostics.log"
TITLE = "Application Settings"


class SettingsPage:
    """Compose and synchronize the Application Settings controls."""

    def __init__(self, model: SettingsModel, actions: AppSettingsActions) -> None:
        self._model = model
        self._actions = actions
        self._theme = ft.Dropdown(
            label="Theme",
            options=[
                ft.DropdownOption(key=Theme.LIGHT.value, text="Light"),
                ft.DropdownOption(key=Theme.DARK.value, text="Dark"),
            ],
            value=Theme.LIGHT.value,
            on_select=self._on_theme,
        )
        self._log_level = ft.Dropdown(
            label="Log level (OFF / DEBUG: all details)",
            options=[ft.DropdownOption(key="OFF"), ft.DropdownOption(key="DEBUG")],
            value="OFF",
            on_select=self._on_log_level,
        )
        self._reaction_time = ft.TextField(
            label="Reaction time (ms)",
            value="0",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=self._on_reaction_time_committed,
            on_blur=self._on_reaction_time_committed,
        )
        self._control = ft.Column(
            controls=[
                ft.Text(TITLE, size=20, weight=ft.FontWeight.BOLD),
                ft.Text("Appearance", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._theme,
                ft.Text("Theme is saved to App Settings immediately."),
                ft.Text("Runtime", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._reaction_time,
                ft.Text("Logging", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._log_level,
                ft.Text(_LOG_FILE_NOTE),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def theme(self) -> ft.Dropdown:
        return self._theme

    @property
    def log_level(self) -> ft.Dropdown:
        return self._log_level

    @property
    def reaction_time(self) -> ft.TextField:
        return self._reaction_time

    def sync(self, settings: EditableAppSettings, permission: EditPermission) -> bool:
        """Sync the App Settings controls; return whether anything changed."""

        changed = False
        if self._theme.value != settings.theme.value:
            self._theme.value = settings.theme.value
            changed = True
        if self._log_level.value != settings.log_level:
            self._log_level.value = settings.log_level
            changed = True
        if self._reaction_time.value != str(settings.reaction_time_ms):
            self._reaction_time.value = str(settings.reaction_time_ms)
            changed = True
        changed |= _set_enabled(self._theme, permission.theme)
        changed |= _set_enabled(self._log_level, permission.log_level)
        changed |= _set_enabled(self._reaction_time, permission.reaction_time)
        return changed

    def _on_theme(self, event: ft.Event[ft.Dropdown]) -> None:
        # Theme is App Settings: it is persisted and applied live, and it never
        # marks the Profile dirty or restarts the runtime.
        try:
            theme = Theme(self._theme.value or Theme.LIGHT.value)
        except ValueError:
            self._actions.set_status("unsupported theme")
            self._request_update()
            return
        self._actions.set_theme(theme)
        self._request_update()

    def _on_log_level(self, event: ft.Event[ft.Dropdown]) -> None:
        # Log level is App Settings: it is persisted and applied live, and it
        # never marks the Profile dirty or restarts the runtime.
        level = self._log_level.value or "DEBUG"
        self._actions.set_log_level(level)
        self._request_update()

    def _on_reaction_time_committed(self, event: ft.Event[ft.TextField]) -> None:
        # Reaction time is App Settings too. Only a committed value (submit or
        # blur) is applied, so a partial number never restarts the runtime.
        try:
            value = int((self._reaction_time.value or "").strip())
        except ValueError:
            self._actions.set_status("reaction time must be a non-negative integer")
            self._request_update()
            return
        self._actions.set_reaction_time(value)
        self._request_update()

    def _request_update(self) -> None:
        try:
            self._control.update()
        except RuntimeError:
            pass


def _set_enabled(control, enabled: bool) -> bool:
    if control.disabled == enabled:
        control.disabled = not enabled
        return True
    return False
