"""Monitor screen composition for the Flet UI.

The screen holds Global Status above Input Preview on the left and the scrolling
Scenario Overview on the right. The left column takes only the width its content
needs, so the divider sits directly after the status and preview and the
Overview takes the remaining space. ``apply`` takes one Monitor snapshot and
pushes it to every panel, so every panel shares one observation read. It returns
a ``MonitorUpdate`` reporting which panels changed, preserving that information
instead of collapsing it into a single bool, so the application can patch just
the changed controls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme

from divergencesplitter_ui.monitor.coordinator import MonitorSnapshot
from divergencesplitter_ui.monitor.global_status import GlobalStatusPanel
from divergencesplitter_ui.monitor.input_preview import InputPreviewPanel
from divergencesplitter_ui.monitor.reset_all import ResetAllButton
from divergencesplitter_ui.monitor.scenario_overview import ScenarioOverviewPanel
from divergencesplitter_ui.presentation import global_status_text
from divergencesplitter_ui.presentation_overview import scenario_overview_view


@dataclass(frozen=True, slots=True)
class MonitorUpdate:
    """Which Monitor panels changed during one ``Monitor.apply`` cycle."""

    global_status: bool = False
    scenario_overview: bool = False

    @property
    def changed(self) -> bool:
        """Whether any panel changed."""

        return self.global_status or self.scenario_overview


class Monitor:
    """Compose the Monitor panels and apply one snapshot to them."""

    def __init__(
        self,
        theme: Theme = Theme.LIGHT,
        *,
        on_reset_all: Callable[[], None] | None = None,
        reset_all: ResetAllButton | None = None,
    ) -> None:
        self.global_status = GlobalStatusPanel()
        self.input_preview = InputPreviewPanel()
        self.scenario_overview = ScenarioOverviewPanel(
            theme, on_reset_all=on_reset_all, reset_all=reset_all
        )
        top = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        self.global_status.control,
                        ft.Divider(),
                        self.input_preview.control,
                    ],
                    spacing=12,
                ),
                ft.VerticalDivider(),
                ft.Container(
                    content=self.scenario_overview.control,
                    expand=True,
                    # No top padding: the Overview title must share its top edge
                    # with Global Status in the left column. Left/right/bottom
                    # insets are kept so the scroll region stays off the divider.
                    padding=ft.Padding.only(left=12, right=12, bottom=12),
                ),
            ],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._control = ft.Column(
            controls=[top],
            expand=True,
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    def set_theme(self, theme: Theme) -> None:
        """Re-target the Monitor's semantic status colors."""

        self.scenario_overview.set_theme(theme)

    def dispose(self) -> None:
        """Release panel-owned tasks; safe to call during shutdown."""

        self.scenario_overview.dispose()

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
        )

    def controls_for_update(self, update: MonitorUpdate) -> tuple[ft.Control, ...]:
        """The panel controls whose state changed and should be patched.

        The application patches exactly these controls, so an unrelated panel
        never gets diffed because another panel changed.
        """

        controls: list[ft.Control] = []
        if update.global_status:
            controls.append(self.global_status.control)
        if update.scenario_overview:
            controls.append(self.scenario_overview.control)
        return tuple(controls)
