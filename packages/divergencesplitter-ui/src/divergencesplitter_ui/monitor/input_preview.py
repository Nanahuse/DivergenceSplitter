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
from divergencesplitter_ui.performance import (
    METRICS,
    PREVIEW_PREPARE,
    PREVIEW_RAW_IMAGE_RENDER,
    PerformanceMetrics,
)
from divergencesplitter_ui.presentation import ObservableDiagnostics

PREVIEW_FPS = 20.0
PREVIEW_INTERVAL_SECONDS = 1.0 / PREVIEW_FPS

_DiagnosticsProvider = Callable[[], ObservableDiagnostics | None]
_StopCheck = Callable[[], bool]


class InputPreviewPanel:
    """Display the latest processed frame on a ``RawImage``."""

    def __init__(self, *, metrics: PerformanceMetrics = METRICS) -> None:
        self._metrics = metrics
        self._image = ft.RawImage()
        self._control = ft.Column(
            controls=[ft.Text("Input Preview"), self._image],
            spacing=4,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    async def render_latest(self, diagnostics: ObservableDiagnostics | None) -> bool:
        """Render the newest processed frame; return whether one was rendered.

        Window teardown can make ``RawImage.render`` fail with a normal
        ``RuntimeError``/``TimeoutError``; those are ignored so the Monitor
        preview can pause and resume. Other exceptions propagate.
        """

        if diagnostics is None:
            return False
        frame = diagnostics.take_latest_processed_frame()
        if frame is None:
            return False
        with self._metrics.measure(PREVIEW_PREPARE):
            prepared = prepare_preview(frame.image)
        try:
            with self._metrics.measure(PREVIEW_RAW_IMAGE_RENDER):
                await self._image.render(prepared)
        except RuntimeError, TimeoutError:
            return False
        return True

    async def stream(
        self,
        diagnostics_provider: _DiagnosticsProvider,
        should_stop: _StopCheck,
        *,
        interval_seconds: float = PREVIEW_INTERVAL_SECONDS,
    ) -> None:
        """Render the latest processed frame until ``should_stop`` is true."""

        while not should_stop():
            await self.render_latest(diagnostics_provider())
            await asyncio.sleep(interval_seconds)
