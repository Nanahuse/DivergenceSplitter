"""Monitor screen composition for the Flet UI.

Only the left column is implemented in this migration step: the Global Status
panel above the Input Preview panel. The right side is an intentionally minimal
placeholder so the future Scenario Overview can replace it without moving the
application lifecycle or the panel code.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.monitor.global_status import GlobalStatusPanel
from divergencesplitter_ui.monitor.input_preview import InputPreviewPanel

_LEFT_COLUMN_WIDTH = 560


class Monitor:
    """Compose the Monitor panels into one control tree."""

    def __init__(self) -> None:
        self.global_status = GlobalStatusPanel()
        self.input_preview = InputPreviewPanel()
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
                    content=ft.Text("Scenario Overview"),
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
