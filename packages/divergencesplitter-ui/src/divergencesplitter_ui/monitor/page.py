"""Monitor screen composition for the Flet UI.

The top area holds Global Status above Input Preview on the left and the
scrolling Scenario Overview on the right; the bottom is the collapsed Scenario
/ Diagnostics. ``apply`` takes one Monitor snapshot and pushes it to every
panel, so the Overview and Diagnostics always share one observation read. It
returns a ``MonitorUpdate`` reporting which panels changed, preserving that
information instead of collapsing it into a single bool, so the application can
patch just the changed controls.
"""

from __future__ import annotations

from dataclasses import dataclass

import flet as ft

from divergencesplitter_ui.monitor.coordinator import MonitorSnapshot
from divergencesplitter_ui.monitor.diagnostics import DiagnosticsPanel
from divergencesplitter_ui.monitor.global_status import GlobalStatusPanel
from divergencesplitter_ui.monitor.input_preview import InputPreviewPanel
from divergencesplitter_ui.monitor.scenario_overview import ScenarioOverviewPanel
from divergencesplitter_ui.presentation import global_status_text
from divergencesplitter_ui.presentation_overview import scenario_overview_view

_LEFT_COLUMN_WIDTH = 560


@dataclass(frozen=True, slots=True)
class MonitorUpdate:
    """Which Monitor panels changed during one ``Monitor.apply`` cycle."""

    global_status: bool = False
    scenario_overview: bool = False
    diagnostics: bool = False

    @property
    def changed(self) -> bool:
        """Whether any panel changed."""

        return self.global_status or self.scenario_overview or self.diagnostics


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

    def apply(self, snapshot: MonitorSnapshot) -> MonitorUpdate:
        """Push one snapshot to the Monitor panels; report which panels changed."""

        return MonitorUpdate(
            global_status=self.global_status.apply(
                global_status_text(snapshot.state, snapshot.metrics)
            ),
            scenario_overview=self.scenario_overview.apply(
                scenario_overview_view(
                    snapshot.tree,
                    snapshot.observations,
                    snapshot.run_infos,
                    snapshot.instance_statuses,
                    snapshot.metrics,
                )
            ),
            diagnostics=self.diagnostics.apply(
                snapshot.tree,
                snapshot.observations,
                snapshot.run_infos,
                snapshot.instance_statuses,
            ),
        )

    def controls_for_update(self, update: MonitorUpdate) -> tuple[ft.Control, ...]:
        """The panel controls whose state changed and should be patched.

        The application patches exactly these controls, so an unrelated panel
        (for example an expanded Diagnostics) is never diffed because another
        panel changed.
        """

        controls: list[ft.Control] = []
        if update.global_status:
            controls.append(self.global_status.control)
        if update.scenario_overview:
            controls.append(self.scenario_overview.control)
        if update.diagnostics:
            controls.append(self.diagnostics.control)
        return tuple(controls)
