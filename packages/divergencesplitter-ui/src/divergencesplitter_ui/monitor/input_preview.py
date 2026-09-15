"""Input Preview panel for the Flet Monitor.

The panel streams the newest processed runtime frame to a ``flet.RawImage``.
Frames are never queued: each iteration consumes the latest available frame and
older frames are dropped, so the preview stays low-latency under load. The
await of ``RawImage.render`` is the backpressure that keeps a single render in
flight and paces the loop to display speed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import flet as ft

from divergencesplitter_ui.frame_preview import prepare_preview
from divergencesplitter_ui.presentation import ObservableDiagnostics

PREVIEW_FPS = 20.0
PREVIEW_INTERVAL_SECONDS = 1.0 / PREVIEW_FPS

_DiagnosticsProvider = Callable[[], ObservableDiagnostics | None]
_StopCheck = Callable[[], bool]


class InputPreviewPanel:
    """Display the latest processed frame on a ``RawImage``."""

    def __init__(self) -> None:
        self._image = ft.RawImage()
        self._control = ft.Column(
            controls=[ft.Text("Input Preview"), self._image],
            spacing=4,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    async def stream(
        self,
        diagnostics_provider: _DiagnosticsProvider,
        should_stop: _StopCheck,
        *,
        interval_seconds: float = PREVIEW_INTERVAL_SECONDS,
    ) -> None:
        """Render the latest processed frame until ``should_stop`` is true.

        Window teardown can make ``RawImage.render`` fail with a normal
        ``RuntimeError``/``TimeoutError``; those end the loop quietly. Other
        exceptions propagate so real defects are not swallowed.
        """

        while not should_stop():
            diagnostics = diagnostics_provider()
            if diagnostics is not None:
                frame = diagnostics.take_latest_processed_frame()
                if frame is not None:
                    try:
                        await self._image.render(prepare_preview(frame.image))
                    except RuntimeError, TimeoutError:
                        return
            await asyncio.sleep(interval_seconds)
