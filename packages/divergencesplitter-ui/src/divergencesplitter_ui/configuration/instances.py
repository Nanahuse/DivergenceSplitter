"""Scenario instances editor for the Flet Configuration page.

Each row edits one ``EditableInstanceConfiguration`` through ``SettingsModel``;
add and remove rebuild the rows so index mapping never drifts. Scenario files
are chosen with the shared file dialog using the same extensions as the Dear
PyGui picker.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from divergencesplitter_ui.configuration.dialogs import SCENARIO_EXTENSIONS, FileDialogs
from divergencesplitter_ui.settings import (
    EditableApplicationConfiguration,
    EditPermission,
    SettingsModel,
)


@dataclass
class _InstanceRow:
    rpc: ft.TextField
    event: ft.TextField
    scenario: ft.TextField
    browse: ft.OutlinedButton
    remove: ft.OutlinedButton


class InstancesSection:
    """Edit the list of LiveSplit-bound scenario instances."""

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
        self._rows: list[_InstanceRow] = []
        self._rows_group = ft.Column(controls=[], spacing=8)
        self._count = -1
        self._control = ft.Column(
            controls=[
                ft.Text("Instances"),
                self._rows_group,
                ft.OutlinedButton(content="Add instance", on_click=self._on_add),
            ],
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    def apply(
        self,
        draft: EditableApplicationConfiguration,
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

    def _rebuild(self, draft: EditableApplicationConfiguration) -> None:
        self._count = len(draft.instances)
        self._rows = [
            self._build_row(index, instance)
            for index, instance in enumerate(draft.instances)
        ]
        self._rows_group.controls = [
            row_control for row in self._rows for row_control in self._row_controls(row)
        ]

    @staticmethod
    def _row_controls(row: _InstanceRow) -> list[ft.Control]:
        return [
            ft.Row(controls=[row.rpc, row.event], spacing=8),
            ft.Row(controls=[row.scenario, row.browse, row.remove], spacing=8),
            ft.Divider(),
        ]

    def _build_row(self, index: int, instance) -> _InstanceRow:
        rpc = ft.TextField(
            label="RPC endpoint",
            value=instance.rpc_endpoint,
            expand=True,
            on_change=lambda e, i=index: self._model.set_instance_rpc_endpoint(
                i, e.control.value
            ),
        )
        event = ft.TextField(
            label="Event endpoint",
            value=instance.event_endpoint,
            expand=True,
            on_change=lambda e, i=index: self._model.set_instance_event_endpoint(
                i, e.control.value
            ),
        )
        scenario = ft.TextField(
            label="Scenario",
            value=instance.scenario,
            expand=True,
            on_change=lambda e, i=index: self._model.set_instance_scenario(
                i, e.control.value
            ),
        )
        browse = ft.OutlinedButton(
            content="Browse...",
            on_click=lambda e, i=index: self._on_browse(i),
        )
        remove = ft.OutlinedButton(
            content="Remove",
            on_click=lambda e, i=index: self._on_remove(i),
        )
        return _InstanceRow(rpc, event, scenario, browse, remove)

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
