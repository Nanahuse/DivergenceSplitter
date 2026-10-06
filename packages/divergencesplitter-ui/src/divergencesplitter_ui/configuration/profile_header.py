"""Shared Profile header for the Flet application.

The header is the always-visible Profile context, shown above every Current
View: the current Profile path, its dirty marker, and the New/Open/Save/Save As
buttons. It only renders the values the application computes; every Profile
operation stays in ``ProfileActions``. Status messages are transient
notifications owned by the application, so the header stays a single row.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme

NO_PROFILE_TEXT = "No profile selected"


class ProfileHeader:
    """Present the current Profile path, dirty marker, and actions."""

    def __init__(
        self,
        *,
        on_new: Callable[[ft.Event[ft.OutlinedButton]], object],
        on_open: Callable[[ft.Event[ft.OutlinedButton]], object],
        on_save: Callable[[ft.Event[ft.OutlinedButton]], object],
        on_save_as: Callable[[ft.Event[ft.OutlinedButton]], object],
    ) -> None:
        self._profile_path = ft.TextField(
            value=NO_PROFILE_TEXT,
            read_only=True,
            expand=True,
            key="profile-path",
        )
        self._new_button = ft.OutlinedButton(
            content="New", on_click=on_new, key="profile-new"
        )
        self._open_button = ft.OutlinedButton(
            content="Open", on_click=on_open, key="profile-open"
        )
        self._save_button = ft.OutlinedButton(
            content="Save", on_click=on_save, disabled=True, key="profile-save"
        )
        self._save_as_button = ft.OutlinedButton(
            content="Save As", on_click=on_save_as, disabled=True, key="profile-save-as"
        )
        self._control = ft.Row(
            controls=[
                self._profile_path,
                self._new_button,
                self._open_button,
                self._save_button,
                self._save_as_button,
            ],
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def profile_path(self) -> ft.TextField:
        return self._profile_path

    @property
    def new_button(self) -> ft.OutlinedButton:
        return self._new_button

    @property
    def open_button(self) -> ft.OutlinedButton:
        return self._open_button

    @property
    def save_button(self) -> ft.OutlinedButton:
        return self._save_button

    @property
    def save_as_button(self) -> ft.OutlinedButton:
        return self._save_as_button

    def set_theme(self, theme: Theme) -> None:
        """Accept a theme; the header has no theme-dependent controls."""

    def sync(
        self,
        *,
        path_text: str,
        new_enabled: bool,
        open_enabled: bool,
        save_enabled: bool,
        save_as_enabled: bool,
    ) -> bool:
        """Render the page's Profile state; return whether anything changed.

        Status is intentionally absent: it is transient notification state, not
        part of the header.
        """

        changed = False
        if self._profile_path.value != path_text:
            self._profile_path.value = path_text
            changed = True
        changed |= _set_enabled(self._new_button, new_enabled)
        changed |= _set_enabled(self._open_button, open_enabled)
        changed |= _set_enabled(self._save_button, save_enabled)
        changed |= _set_enabled(self._save_as_button, save_as_enabled)
        return changed


def _set_enabled(control, enabled: bool) -> bool:
    if control.disabled == enabled:
        control.disabled = not enabled
        return True
    return False
