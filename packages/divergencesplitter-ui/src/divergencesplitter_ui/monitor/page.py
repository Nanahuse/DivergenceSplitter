"""Monitor screen composition for the Flet UI.

The top area holds Global Status above Input Preview on the left and the
scrolling Scenario Overview on the right; the bottom is the collapsed Scenario
/ Diagnostics. ``apply`` takes one Monitor snapshot and pushes it to every
panel, so the Overview and Diagnostics always share one observation read. It
returns whether anything changed so the application only repaints when it must.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.monitor.coordinator import MonitorSnapshot
from divergencesplitter_ui.monitor.diagnostics import DiagnosticsPanel
from divergencesplitter_ui.monitor.global_status import GlobalStatusPanel
from divergencesplitter_ui.monitor.input_preview import InputPreviewPanel
from divergencesplitter_ui.monitor.scenario_overview import ScenarioOverviewPanel
from divergencesplitter_ui.presentation import global_status_text
from divergencesplitter_ui.presentation_overview import scenario_overview_view

_LEFT_COLUMN_WIDTH = 560


class Monitor:
    """Compose the Monitor panels and apply one snapshot to them."""

    def __init__(self) -> None:
        self.global_status = GlobalStatusPanel()
        self.input_preview = InputPreviewPanel()
        self.scenario_overview = ScenarioOverviewPanel()
        self.diagnostics = DiagnosticsPanel()
        top = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        self.global_status.control,
                        ft.Divider(),
                        self.input_preview.control,
                    ],
                    width=_LEFT_COLUMN_WIDTH,
                    spacing=12,
                ),
                ft.VerticalDivider(),
                ft.Container(
                    content=self.scenario_overview.control,
                    expand=True,
                    padding=12,
                ),
            ],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._control = ft.Column(
            controls=[top, ft.Divider(), self.diagnostics.control],
            expand=True,
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    def apply(self, snapshot: MonitorSnapshot) -> bool:
        """Push one snapshot to the Monitor panels; report whether it changed."""

        changed = self.global_status.apply(
            global_status_text(snapshot.state, snapshot.metrics)
        )
        changed |= self.scenario_overview.apply(
            scenario_overview_view(
                snapshot.tree,
                snapshot.observations,
                snapshot.run_infos,
                snapshot.instance_statuses,
                snapshot.metrics,
            )
        )
        changed |= self.diagnostics.apply(
            snapshot.tree,
            snapshot.observations,
            snapshot.run_infos,
            snapshot.instance_statuses,
        )
        return changed
