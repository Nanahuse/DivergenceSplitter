"""Desktop application wiring the screen to one owned ``SessionController``.

The application constructs the same session pipeline as the command line, owns
one controller, and drives the Dear PyGui render loop on the main thread. The
screen reads state and observations from the controller's diagnostics and never
re-implements capture, processing, or Bridge communication.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.about_window import AboutWindow
from divergencesplitter_ui.error_window import ErrorWindow
from divergencesplitter_ui.license_window import LicenseWindow
from divergencesplitter_ui.presentation import (
    ObservableDiagnostics,
    ScreenPresenter,
)
from divergencesplitter_ui.renderer import ScreenRenderer
from divergencesplitter_ui.session import (
    ApplicationRuntimeFactory,
    DefaultConfigurationLoader,
    DefaultScenarioLoader,
    DefaultSourceBuilder,
    OperationalDiagnosticsFactory,
    SessionController,
)
from divergencesplitter_ui.settings import SettingsModel, WindowsCameraEnumerator
from divergencesplitter_ui.settings_window import SettingsWindow


class DesktopApplication:
    """Own one session and present it through a Dear PyGui render loop."""

    def __init__(
        self,
        controller: SessionController,
        *,
        initial_configuration: Path | None = None,
        presenter: ScreenPresenter | None = None,
        settings_model: SettingsModel | None = None,
    ) -> None:
        self._controller = controller
        self._renderer = ScreenRenderer(presenter)
        self._initial_configuration = initial_configuration
        model = settings_model or SettingsModel(WindowsCameraEnumerator())
        self._settings = SettingsWindow(controller, model)
        self._licenses = LicenseWindow()
        self._about = AboutWindow(self._licenses)
        self._errors = ErrorWindow()

    def run(self) -> None:
        context_created = False
        try:
            dpg.create_context()
            context_created = True
            self._renderer.build()
            self._settings.build()
            self._settings.build_main_shortcut(ScreenRenderer.SCENARIO_GROUP_TAG)
            self._about.build()
            self._about.build_main_shortcut(ScreenRenderer.SCENARIO_GROUP_TAG)
            self._licenses.build()
            self._errors.build()
            dpg.create_viewport(
                title="DivergenceSplitter",
                width=1200,
                height=900,
            )
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(ScreenRenderer.WINDOW_TAG, True)
            if self._initial_configuration is not None:
                self._settings.open_configuration(self._initial_configuration)
            while dpg.is_dearpygui_running():
                state = self._controller.state
                result = self._controller.result
                self._settings.tick(state)
                self._errors.tick(result)
                self._renderer.tick(
                    state,
                    self._observable(),
                )
                dpg.render_dearpygui_frame()
        finally:
            self.stop(destroy_context=context_created)

    def _observable(self) -> ObservableDiagnostics | None:
        return self._controller.diagnostics

    def stop(self, *, destroy_context: bool = True) -> None:
        self._controller.request_stop()
        self._controller.join()
        if destroy_context:
            dpg.destroy_context()


def build_controller(*, stream: TextIO) -> SessionController:
    """Construct a session pipeline identical to the command line's."""

    return SessionController(
        configuration_loader=DefaultConfigurationLoader(),
        scenario_loader=DefaultScenarioLoader(),
        source_builder=DefaultSourceBuilder(),
        runtime_factory=ApplicationRuntimeFactory(),
        diagnostics_factory=OperationalDiagnosticsFactory(stream),
    )


def run_configuration(configuration: Path | None = None) -> None:
    """Run the UI and optionally open one configuration on startup."""

    controller = build_controller(stream=sys.stderr)
    application = DesktopApplication(
        controller,
        initial_configuration=configuration,
    )
    application.run()
