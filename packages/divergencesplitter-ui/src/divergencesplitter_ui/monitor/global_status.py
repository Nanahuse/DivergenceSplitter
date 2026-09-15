"""Global Status panel for the Flet Monitor.

The panel only owns its widgets. Formatting is delegated to the pure
``global_status_text`` helper, so the values shown here are the same values the
presentation layer can be tested against without a GUI.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.presentation import (
    UNMEASURED_FPS,
    GlobalStatusText,
)

_STATE_LABEL = "State"
_INPUT_LABEL = "Input"
_PROCESSING_LABEL = "Processing"
_LABEL_WIDTH = 110


class GlobalStatusPanel:
    """Present session state and throughput metrics as label/value rows."""

    def __init__(self) -> None:
        self._state = ft.Text("—")
        self._input_fps = ft.Text(UNMEASURED_FPS)
        self._processing_fps = ft.Text(UNMEASURED_FPS)
        self._control = ft.Column(
            controls=[
                ft.Text("Global Status"),
                self._row(_STATE_LABEL, self._state),
                self._row(_INPUT_LABEL, self._input_fps),
                self._row(_PROCESSING_LABEL, self._processing_fps),
            ],
            spacing=4,
        )

    @staticmethod
    def _row(label: str, value: ft.Text) -> ft.Control:
        return ft.Row(
            controls=[ft.Text(label, width=_LABEL_WIDTH), value],
            spacing=12,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    def apply(self, status: GlobalStatusText) -> bool:
        """Write one formatted status onto the widgets.

        Returns whether any displayed value changed, so the Monitor only asks
        the page to repaint when something actually differs.
        """

        changed = False
        for text, value in (
            (self._state, status.state),
            (self._input_fps, status.input_fps),
            (self._processing_fps, status.processing_fps),
        ):
            if text.value != value:
                text.value = value
                changed = True
        return changed
