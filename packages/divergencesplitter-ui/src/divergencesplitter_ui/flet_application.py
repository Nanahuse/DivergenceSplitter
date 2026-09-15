"""Flet application hosting the Monitor on the Flet asyncio event loop.

The Flet UI runs on the main thread's asyncio event loop while the
``SessionController`` keeps owning its own non-daemon runtime thread. Nothing
about the runtime is made async: only the GUI status and preview tasks are
coroutines. Shutdown stops those tasks, requests a runtime stop, and performs
the blocking thread join off the event loop before destroying the window.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import flet as ft

from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.page import Monitor
from divergencesplitter_ui.session import SessionController

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 900
WINDOW_TITLE = "DivergenceSplitter"
MONITOR_INTERVAL_SECONDS = 0.1
_MAIN_POLL_SECONDS = 0.1


class FletApplication:
    """Own one session and present it through a Flet event loop."""

    def __init__(
        self,
        controller: SessionController,
        *,
        initial_configuration: Path | None = None,
        coordinator: MonitorUpdateCoordinator | None = None,
    ) -> None:
        self._controller = controller
        self._initial_configuration = initial_configuration
        self._coordinator = coordinator or MonitorUpdateCoordinator(controller)
        self._page: ft.Page | None = None
        self._monitor: Monitor | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._shutdown_started = False

    @property
    def stopping(self) -> bool:
        """Whether shutdown has begun and background tasks should wind down."""

        return self._stopping

    def run(self) -> None:
        """Run the Flet app until the window is closed and cleaned up."""

        ft.run(self._main)

    def start_session(self, configuration: Path | None = None) -> None:
        """Start the controller's existing session thread when a path exists."""

        path = self._initial_configuration if configuration is None else configuration
        if path is not None:
            self._controller.start(path)

    async def _main(self, page: ft.Page) -> None:
        self._page = page
        page.title = WINDOW_TITLE
        page.window.width = WINDOW_WIDTH
        page.window.height = WINDOW_HEIGHT
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event

        self._monitor = Monitor()
        page.add(self._monitor.control)
        page.update()

        self.start_session()

        self._tasks = [
            asyncio.create_task(self._monitor_loop()),
            asyncio.create_task(self._preview_loop()),
        ]
        try:
            while not self._stopping:
                await asyncio.sleep(_MAIN_POLL_SECONDS)
        finally:
            await self.shutdown()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        # Intercept the native close so the runtime is stopped and the window is
        # destroyed only after cleanup. The main loop performs the actual
        # teardown once it observes ``stopping``.
        if event.type == ft.WindowEventType.CLOSE:
            self._stopping = True

    async def _monitor_loop(self) -> None:
        await self._apply_monitor()
        while not self._stopping:
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
            await self._apply_monitor()

    async def _apply_monitor(self) -> None:
        monitor = self._monitor
        if monitor is None:
            return
        snapshot = self._coordinator.snapshot()
        if monitor.apply(snapshot) and self._page is not None:
            self._page.update()

    async def _preview_loop(self) -> None:
        monitor = self._monitor
        if monitor is None:
            return
        await monitor.input_preview.stream(
            lambda: self._controller.diagnostics,
            lambda: self._stopping,
        )

    async def shutdown(self) -> None:
        """Stop the GUI tasks and the runtime, then destroy the window.

        Safe to call more than once: later calls return immediately. The
        blocking ``join`` runs through ``asyncio.to_thread`` so the Flet event
        loop is never blocked.
        """

        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._stopping = True
        await self._stop_tasks()
        self._controller.request_stop()
        await asyncio.to_thread(self._controller.join)
        await self._close_window()

    async def _stop_tasks(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks = []

    async def _close_window(self) -> None:
        page = self._page
        if page is None:
            return
        with contextlib.suppress(Exception):
            await page.window.destroy()
