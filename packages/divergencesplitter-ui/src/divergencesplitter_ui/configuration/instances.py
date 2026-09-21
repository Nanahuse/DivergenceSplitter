"""Scenario instances editor for the Flet Configuration page.

Each card edits one ``EditableInstanceConfiguration`` through ``SettingsModel``:
its scenario file and the LiveSplit connection endpoints. Add and remove rebuild
the cards so index mapping never drifts. The internal ``instances`` model
terminology is kept; the UI presents each entry as a Scenario.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from divergencesplitter_ui.configuration.dialogs import SCENARIO_EXTENSIONS, FileDialogs
from divergencesplitter_ui.settings import (
    EditableProfile,
    EditPermission,
    SettingsModel,
)


@dataclass
class InstanceRow:
    number: int
    rpc: ft.TextField
    event: ft.TextField
    scenario: ft.TextField
    browse: ft.OutlinedButton
    remove: ft.OutlinedButton


class InstancesSection:
    """Edit the list of LiveSplit-bound scenario instances as cards."""

    def __init__(
        self,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        on_changed: Callable[[], None],
    ) -> None:
        self._model = model
        self._dialogs = dialogs
        self._on_changed = on_changed
        self._rows: list[InstanceRow] = []
        self._rows_group = ft.Column(controls=[], spacing=12)
        self._count = -1
        self._control = ft.Column(
            controls=[
                ft.Text("Scenarios & Connections", size=16, weight=ft.FontWeight.BOLD),
                self._rows_group,
                ft.OutlinedButton(
                    content="Add Scenario",
                    on_click=self._on_add,
                    key="profile-add-scenario",
                ),
            ],
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def rows(self) -> tuple[InstanceRow, ...]:
        """The current Scenario cards, exposed for read-only UI assertions."""

        return tuple(self._rows)

    def apply(
        self,
        draft: EditableProfile,
        permission: EditPermission,
    ) -> bool:
        changed = False
        if len(draft.instances) != self._count:
            self._rebuild(draft)
            changed = True
        else:
            for index, row in enumerate(self._rows):
                instance = draft.instances[index]
                changed |= self._set(row.rpc, instance.rpc_endpoint)
                changed |= self._set(row.event, instance.event_endpoint)
                changed |= self._set(row.scenario, instance.scenario)
        for row in self._rows:
            enabled = permission.instances
            for control in (row.rpc, row.event, row.scenario, row.browse, row.remove):
                changed |= self._set_enabled(control, enabled)
        return changed

    def _rebuild(self, draft: EditableProfile) -> None:
        self._count = len(draft.instances)
        self._rows = [
            self._build_row(index, instance)
            for index, instance in enumerate(draft.instances)
        ]
        self._rows_group.controls = [
            row_control for row in self._rows for row_control in self._row_controls(row)
        ]

    @staticmethod
    def _row_controls(row: InstanceRow) -> list[ft.Control]:
        return [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(
                            f"Scenario {row.number}",
                            size=15,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Row(controls=[row.scenario, row.browse], spacing=8),
                        ft.Text("LiveSplit Connection", weight=ft.FontWeight.BOLD),
                        row.rpc,
                        row.event,
                        ft.Row(
                            controls=[row.remove],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=6,
                ),
                border=ft.Border.all(1, ft.Colors.OUTLINE),
                border_radius=8,
                padding=12,
            )
        ]

    def _build_row(self, index: int, instance) -> InstanceRow:
        return InstanceRow(
            number=index + 1,
            rpc=ft.TextField(
                label="RPC endpoint",
                value=instance.rpc_endpoint,
                on_change=lambda e, i=index: self._model.set_instance_rpc_endpoint(
                    i, e.control.value
                ),
                key=f"profile-rpc-{index}",
            ),
            event=ft.TextField(
                label="Event endpoint",
                value=instance.event_endpoint,
                on_change=lambda e, i=index: self._model.set_instance_event_endpoint(
                    i, e.control.value
                ),
                key=f"profile-event-{index}",
            ),
            scenario=ft.TextField(
                label="Scenario file",
                value=instance.scenario,
                expand=True,
                on_change=lambda e, i=index: self._model.set_instance_scenario(
                    i, e.control.value
                ),
                key=f"profile-scenario-{index}",
            ),
            browse=ft.OutlinedButton(
                content="Browse...",
                on_click=lambda e, i=index: self._on_browse(i),
            ),
            remove=ft.OutlinedButton(
                content="Remove",
                on_click=lambda e, i=index: self._on_remove(i),
                key=f"profile-remove-scenario-{index}",
            ),
        )

    def _on_add(self, event: ft.Event[ft.OutlinedButton]) -> None:
        draft = self._model.add_instance()
        if draft is not None:
            self._rebuild(draft)
            self._on_changed()
            self._request_page_update()

    def _on_remove(self, index: int) -> None:
        draft = self._model.remove_instance(index)
        if draft is not None:
            self._rebuild(draft)
            self._on_changed()
            self._request_page_update()

    async def _on_browse(self, index: int) -> None:
        path = await self._dialogs.open_file(
            title="Select script file", extensions=SCENARIO_EXTENSIONS
        )
        if path is None:
            return
        if self._model.set_instance_scenario(index, str(path)) is None:
            return
        if index < len(self._rows):
            self._rows[index].scenario.value = str(path)
            self._request_update(self._rows[index].scenario)

    def _request_update(self, control: ft.Control) -> None:
        try:
            control.update()
        except RuntimeError:
            pass

    def _request_page_update(self) -> None:
        self._request_update(self._rows_group)

    @staticmethod
    def _set(control: ft.TextField, value: str) -> bool:
        if control.value == value:
            return False
        control.value = value
        return True

    @staticmethod
    def _set_enabled(control, enabled: bool) -> bool:
        if control.disabled == enabled:
            control.disabled = not enabled
            return True
        return False
