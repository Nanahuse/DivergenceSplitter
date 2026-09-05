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


class DesktopApplication:
    """Own one session and present it through a Dear PyGui render loop."""

    def __init__(
        self,
        controller: SessionController,
        *,
        presenter: ScreenPresenter | None = None,
    ) -> None:
        self._controller = controller
        self._renderer = ScreenRenderer(presenter)

    def run(self) -> None:
        context_created = False
        try:
            dpg.create_context()
            context_created = True
            self._renderer.build()
            dpg.create_viewport(
                title="DivergenceSplitter",
                width=1200,
                height=900,
            )
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(ScreenRenderer.WINDOW_TAG, True)
            while dpg.is_dearpygui_running():
                self._renderer.tick(
                    self._controller.state,
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


def run_configuration(configuration: Path) -> None:
    """Start one session from a configuration path and run the UI loop."""

    controller = build_controller(stream=sys.stderr)
    controller.start(configuration)
    application = DesktopApplication(controller)
    application.run()
