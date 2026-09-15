"""Monitor screen composition for the Flet UI.

The left column holds Global Status above Input Preview and never scrolls; the
right column is the scrolling Scenario Overview. ``apply`` takes one Monitor
snapshot, formats it, and pushes it to both panels, returning whether anything
changed so the application only repaints the page when it must.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.monitor.coordinator import MonitorSnapshot
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
        self._control = ft.Row(
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

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    def apply(self, snapshot: MonitorSnapshot) -> bool:
        """Push one snapshot to the Monitor panels; report whether it changed."""

        status_changed = self.global_status.apply(
            global_status_text(snapshot.state, snapshot.metrics)
        )
        overview_changed = self.scenario_overview.apply(
            scenario_overview_view(
                snapshot.tree,
                snapshot.observations,
                snapshot.run_infos,
                snapshot.instance_statuses,
                snapshot.metrics,
            )
        )
        return status_changed or overview_changed
