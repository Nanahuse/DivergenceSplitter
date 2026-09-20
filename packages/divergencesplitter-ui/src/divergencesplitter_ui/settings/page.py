"""Application Settings screen for the Flet front end.

The screen edits App Settings only: the appearance theme, the reaction time, and
the logging level. It is presentation, delegating persistence and application to
``AppSettingsActions``. Editing a control updates only the model's App Settings
draft; nothing is saved or applied until the user presses Apply. Theme, log
level, and reaction time live in the App Settings file rather than a Profile, so
they never mark the Profile dirty and the screen stays fully usable without a
selected Profile.
"""

from __future__ import annotations

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme

from divergencesplitter_ui.settings.actions import AppSettingsActions
from divergencesplitter_ui.settings.model import (
    AppSettingsDraft,
    EditPermission,
    SettingsModel,
)

_LOG_FILE_NOTE = "DEBUG log: see diagnostics.log"
TITLE = "Application Settings"
_NOTE = "Edit the values, then select Apply to save and apply them."


class SettingsPage:
    """Compose and synchronize the Application Settings controls."""

    def __init__(self, model: SettingsModel, actions: AppSettingsActions) -> None:
        self._model = model
        self._actions = actions
        self._editable = True
        self._theme = ft.Dropdown(
            label="Theme",
            options=[
                ft.DropdownOption(key=Theme.LIGHT.value, text="Light"),
                ft.DropdownOption(key=Theme.DARK.value, text="Dark"),
            ],
            value=Theme.LIGHT.value,
            on_select=self._on_theme,
            key="settings-theme",
        )
        self._log_level = ft.Dropdown(
            label="Log level (OFF / DEBUG: all details)",
            options=[ft.DropdownOption(key="OFF"), ft.DropdownOption(key="DEBUG")],
            value="OFF",
            on_select=self._on_log_level,
            key="settings-log-level",
        )
        self._reaction_time = ft.TextField(
            label="Reaction time (ms)",
            value="0",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_reaction_time_changed,
            key="settings-reaction-time",
        )
        self._apply = ft.FilledButton(
            content="Apply",
            on_click=self._on_apply,
            disabled=True,
            key="settings-apply",
        )
        self._status = ft.Text("")
        self._control = ft.Column(
            controls=[
                ft.Text(TITLE, size=20, weight=ft.FontWeight.BOLD),
                ft.Text(_NOTE),
                ft.Text("Appearance", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._theme,
                ft.Text("Runtime", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._reaction_time,
                ft.Text("Logging", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self._log_level,
                ft.Text(_LOG_FILE_NOTE),
                ft.Divider(),
                self._apply,
                self._status,
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

    @property
    def apply(self) -> ft.FilledButton:
        return self._apply

    @property
    def status(self) -> ft.Text:
        return self._status

    def sync(self, draft: AppSettingsDraft, permission: EditPermission) -> bool:
        """Sync the controls from the draft; return whether anything changed.

        The draft is the source of truth, so a periodic sync never reverts a
        value the user is still editing.
        """

        self._editable = permission.settings
        changed = False
        if self._theme.value != draft.theme.value:
            self._theme.value = draft.theme.value
            changed = True
        if self._log_level.value != draft.log_level:
            self._log_level.value = draft.log_level
            changed = True
        if self._reaction_time.value != draft.reaction_time_text:
            self._reaction_time.value = draft.reaction_time_text
            changed = True
        if self._status.value != self._actions.status:
            self._status.value = self._actions.status
            changed = True
        changed |= _set_enabled(self._theme, permission.theme)
        changed |= _set_enabled(self._log_level, permission.log_level)
        changed |= _set_enabled(self._reaction_time, permission.reaction_time)
        changed |= _set_enabled(self._apply, self._apply_enabled())
        return changed

    def _apply_enabled(self) -> bool:
        return self._editable and self._model.app_settings_dirty

    def _on_theme(self, event: ft.Event[ft.Dropdown]) -> None:
        # Editing only updates the draft; Apply persists and reflects it.
        try:
            theme = Theme(self._theme.value or Theme.LIGHT.value)
        except ValueError:
            return
        self._model.edit_theme(theme)
        self._refresh_apply()

    def _on_log_level(self, event: ft.Event[ft.Dropdown]) -> None:
        level = self._log_level.value or "OFF"
        self._model.edit_log_level(level)
        self._refresh_apply()

    def _on_reaction_time_changed(self, event: ft.Event[ft.TextField]) -> None:
        self._model.edit_reaction_time(self._reaction_time.value or "")
        self._refresh_apply()

    def _on_apply(self, event: ft.Event[ft.Button]) -> None:
        self._actions.apply()
        self._refresh_apply()
        self._request_update()

    def _refresh_apply(self) -> None:
        changed = _set_enabled(self._apply, self._apply_enabled())
        if self._status.value != self._actions.status:
            self._status.value = self._actions.status
            changed = True
        if changed:
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
