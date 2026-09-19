"""System tab for the Flet Configuration page.

The tab edits App Settings only: the appearance theme, the reaction time, and the
logging level. It is presentation, delegating the persistence and application
to the existing ``ProfileActions``. Theme, log level, and reaction time live in
the App Settings file rather than a Profile, so they never mark the Profile
dirty and the tab stays fully usable without a selected Profile.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme

from divergencesplitter_ui.settings import EditableAppSettings, EditPermission

_LOG_FILE_NOTE = "DEBUG log: see diagnostics.log"


class SystemTab:
    """Compose the App Settings controls shown by the System tab."""

    def __init__(
        self,
        *,
        on_theme: Callable[[ft.Event[ft.Dropdown]], object],
        on_log_level: Callable[[ft.Event[ft.Dropdown]], object],
        on_reaction_time_committed: Callable[[ft.Event[ft.TextField]], object],
    ) -> None:
        self._theme = ft.Dropdown(
            label="Theme",
            options=[
                ft.DropdownOption(key=Theme.LIGHT.value, text="Light"),
                ft.DropdownOption(key=Theme.DARK.value, text="Dark"),
            ],
            value=Theme.LIGHT.value,
            on_select=on_theme,
        )
        self._log_level = ft.Dropdown(
            label="Logging (OFF / DEBUG: all details)",
            options=[ft.DropdownOption(key="OFF"), ft.DropdownOption(key="DEBUG")],
            value="OFF",
            on_select=on_log_level,
        )
        self._reaction_time = ft.TextField(
            label="Reaction time (ms)",
            value="0",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=on_reaction_time_committed,
            on_blur=on_reaction_time_committed,
        )
        self._control = ft.Column(
            controls=[
                ft.Text("System", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("Appearance", weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._theme,
                ft.Text("Theme is saved to App Settings immediately."),
                ft.Text("Runtime", weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._reaction_time,
                ft.Text("Diagnostics", weight=ft.FontWeight.BOLD),
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


def _set_enabled(control, enabled: bool) -> bool:
    if control.disabled == enabled:
        control.disabled = not enabled
        return True
    return False
