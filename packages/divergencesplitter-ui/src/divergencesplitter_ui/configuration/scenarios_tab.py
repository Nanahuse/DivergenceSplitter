"""Scenarios & Connections tab for the Flet Configuration page.

The tab edits ``Profile.instances`` and wraps the existing ``InstancesSection``
so each entry is shown as a Scenario card with its LiveSplit connection. When no
Profile is selected it shows an empty state; System stays fully usable.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from divergencesplitter_ui.configuration.dialogs import FileDialogs
from divergencesplitter_ui.configuration.instances import InstancesSection
from divergencesplitter_ui.settings import (
    EditableProfile,
    EditPermission,
    SettingsModel,
)

_EMPTY_MESSAGE = "Create or open a Profile to configure scenarios and connections."


class ScenariosTab:
    """Compose the scenario cards and the no-Profile empty state."""

    def __init__(
        self,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        on_changed: Callable[[], None],
    ) -> None:
        self.section = InstancesSection(model, dialogs, on_changed=on_changed)
        self._empty = ft.Column(
            controls=[
                ft.Text("No Profile selected."),
                ft.Text(_EMPTY_MESSAGE),
            ],
            spacing=4,
            visible=False,
        )
        self._body = ft.Column(
            controls=[self.section.control],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._control = ft.Column(
            controls=[self._empty, self._body],
            spacing=8,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    def set_profile_present(self, present: bool) -> bool:
        changed = False
        if self._empty.visible == present:
            self._empty.visible = not present
            changed = True
        if self._body.visible != present:
            self._body.visible = present
            changed = True
        return changed

    def apply(self, draft: EditableProfile, permission: EditPermission) -> bool:
        changed = self.set_profile_present(True)
        changed |= self.section.apply(draft, permission)
        return changed
