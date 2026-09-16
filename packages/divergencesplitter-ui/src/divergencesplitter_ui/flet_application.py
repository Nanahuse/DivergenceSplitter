"""Flet application hosting the Monitor and Configuration pages.

The Flet UI runs on the main thread's asyncio event loop while the
``SessionController`` keeps owning its own non-daemon runtime thread. The
application owns navigation, task ownership, and shutdown; the pages own their
own controls. Shutdown stops every task, requests a runtime stop, and performs
the blocking thread join off the event loop before destroying the window.
"""

from __future__ import annotations

import asyncio
import contextlib
from enum import StrEnum
from pathlib import Path

import flet as ft
from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_configuration,
)

from divergencesplitter_ui.about_page import AboutView
from divergencesplitter_ui.configuration.dialogs import FletFileDialogs
from divergencesplitter_ui.configuration.page import ConfigurationPage
from divergencesplitter_ui.error_dialog import ErrorDialog
from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.diagnostics import DiagnosticsPanel
from divergencesplitter_ui.monitor.input_preview import PREVIEW_INTERVAL_SECONDS
from divergencesplitter_ui.monitor.page import Monitor
from divergencesplitter_ui.session import SessionController
from divergencesplitter_ui.settings import SettingsModel, WindowsCameraEnumerator

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 900
WINDOW_TITLE = "DivergenceSplitter"
MONITOR_INTERVAL_SECONDS = 0.1
CONFIGURATION_PREVIEW_SECONDS = 1.0 / 15.0
_MAIN_POLL_SECONDS = 0.1


class AppView(StrEnum):
    """The top-level page the navigation rail is showing."""

    MONITOR = "monitor"
    DIAGNOSTICS = "diagnostics"
    CONFIGURATION = "configuration"
    ABOUT = "about"


_VIEW_ORDER = (
    AppView.MONITOR,
    AppView.DIAGNOSTICS,
    AppView.CONFIGURATION,
    AppView.ABOUT,
)


class FletApplication:
    """Own one session and present it through a Flet event loop."""

    def __init__(
        self,
        controller: SessionController,
        *,
        initial_configuration: Path | None = None,
        coordinator: MonitorUpdateCoordinator | None = None,
        settings_model: SettingsModel | None = None,
    ) -> None:
        self._controller = controller
        self._initial_configuration = initial_configuration
        self._coordinator = coordinator or MonitorUpdateCoordinator(controller)
        self._model = (
            settings_model
            if settings_model is not None
            else SettingsModel(WindowsCameraEnumerator())
        )
        self._page: ft.Page | None = None
        self._monitor: Monitor | None = None
        self._diagnostics: DiagnosticsPanel | None = None
        self._configuration: ConfigurationPage | None = None
        self._about: AboutView | None = None
        self._error_dialog: ErrorDialog | None = None
        self._monitor_view: ft.Container | None = None
        self._diagnostics_view: ft.Container | None = None
        self._configuration_view: ft.Container | None = None
        self._about_view: ft.Container | None = None
        self._navigation: ft.NavigationRail | None = None
        self._active_view = AppView.MONITOR
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._shutdown_started = False

    @property
    def stopping(self) -> bool:
        """Whether shutdown has begun and background tasks should wind down."""

        return self._stopping

    @property
    def active_view(self) -> AppView:
        return self._active_view

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

        file_picker = ft.FilePicker()
        dialogs = FletFileDialogs(page, file_picker)
        self._monitor = Monitor()
        self._diagnostics = DiagnosticsPanel()
        self._configuration = ConfigurationPage(self._controller, self._model, dialogs)
        self._about = AboutView()
        self._error_dialog = ErrorDialog(
            show_dialog=page.show_dialog,
            hide_dialog=page.pop_dialog,
        )
        if self._initial_configuration is not None:
            self._load_initial_configuration(self._initial_configuration)

        self._monitor_view = ft.Container(self._monitor.control, expand=True)
        self._diagnostics_view = ft.Container(
            self._diagnostics.control, expand=True, visible=False
        )
        self._configuration_view = ft.Container(
            self._configuration.control, expand=True, visible=False
        )
        self._about_view = ft.Container(self._about.control, expand=True, visible=False)
        navigation = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.MONITOR, label="Monitor"),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TROUBLESHOOT, label="Diagnostics"
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS, label="Configuration"
                ),
                ft.NavigationRailDestination(icon=ft.Icons.INFO, label="About"),
            ],
            on_change=self._on_navigate,
        )
        self._navigation = navigation
        page.add(
            ft.Row(
                controls=[
                    navigation,
                    ft.VerticalDivider(),
                    ft.Column(
                        controls=[
                            self._monitor_view,
                            self._diagnostics_view,
                            self._configuration_view,
                            self._about_view,
                        ],
                        expand=True,
                    ),
                ],
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )
        page.update()

        self.start_session()
        self._configuration.populate()

        self._tasks = [
            asyncio.create_task(self._monitor_loop()),
            asyncio.create_task(self._input_preview_loop()),
            asyncio.create_task(self._configuration_preview_loop()),
        ]
        try:
            while not self._stopping:
                await asyncio.sleep(_MAIN_POLL_SECONDS)
        finally:
            await self.shutdown()

    def _load_initial_configuration(self, path: Path) -> None:
        if self._configuration is None:
            return
        try:
            configuration = load_configuration(path)
        except (ConfigurationFileError, ConfigurationValidationError) as error:
            self._configuration.actions.set_status(str(error))
            return
        self._model.open_configuration(configuration, path)

    def _on_navigate(self, event: ft.Event[ft.NavigationRail]) -> None:
        selected = int(event.control.selected_index or 0)
        view = (
            _VIEW_ORDER[selected]
            if 0 <= selected < len(_VIEW_ORDER)
            else AppView.MONITOR
        )
        self._active_view = view
        for candidate, container in (
            (AppView.MONITOR, self._monitor_view),
            (AppView.DIAGNOSTICS, self._diagnostics_view),
            (AppView.CONFIGURATION, self._configuration_view),
            (AppView.ABOUT, self._about_view),
        ):
            if container is not None:
                container.visible = candidate is view
        if self._page is not None:
            self._page.update()

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
        snapshot = self._coordinator.snapshot()
        targets: list[ft.Control] = []
        if self._active_view is AppView.MONITOR and self._monitor is not None:
            update = self._monitor.apply(snapshot)
            targets.extend(self._monitor.controls_for_update(update))
        if self._diagnostics is not None:
            diagnostics_visible = self._active_view is AppView.DIAGNOSTICS
            changed = self._diagnostics.apply(
                snapshot.tree,
                snapshot.observations,
                snapshot.run_infos,
                snapshot.instance_statuses,
                visible=diagnostics_visible,
            )
            if changed:
                targets.append(self._diagnostics.control)
        if self._configuration is not None:
            visible = self._active_view is AppView.CONFIGURATION
            changed = self._configuration.tick(self._controller.state, visible=visible)
            if visible and changed:
                targets.append(self._configuration.control)
        if self._error_dialog is not None:
            # Showing or hiding a dialog already patches the dialog controls, so
            # it is intentionally kept out of the panel repaint targets.
            self._error_dialog.tick(self._controller.result)
        if targets and self._page is not None:
            self._page.update(*targets)

    async def _input_preview_loop(self) -> None:
        monitor = self._monitor
        if monitor is None:
            return
        while not self._stopping:
            if self._active_view is AppView.MONITOR:
                await monitor.input_preview.render_latest(self._controller.diagnostics)
            await asyncio.sleep(PREVIEW_INTERVAL_SECONDS)

    async def _configuration_preview_loop(self) -> None:
        while not self._stopping:
            await self._apply_configuration_preview()
            await asyncio.sleep(CONFIGURATION_PREVIEW_SECONDS)

    async def _apply_configuration_preview(self) -> None:
        configuration = self._configuration
        if configuration is None or self._active_view is not AppView.CONFIGURATION:
            return
        if not await configuration.pump_preview():
            return
        if self._page is not None:
            self._page.update(*configuration.preview_update_targets())

    async def shutdown(self) -> None:
        """Stop the GUI tasks and the runtime, then destroy the window.

        Safe to call more than once: later calls return immediately. Blocking
        joins run through ``asyncio.to_thread`` so the Flet event loop is never
        blocked.
        """

        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._stopping = True
        await self._stop_tasks()
        if self._configuration is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._configuration.teardown)
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
