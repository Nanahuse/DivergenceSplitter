"""GUI-independent construction of one configured session pipeline.

Both the Dear PyGui and Flet front ends build the same ``SessionController``
here so their runtime wiring can never diverge. This module must stay free of
any GUI framework import; only the session and runtime construction path is
owned here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from divergencesplitter_ui.logs import log_file_path
from divergencesplitter_ui.session import (
    ApplicationRuntimeFactory,
    DefaultConfigurationLoader,
    DefaultScenarioLoader,
    DefaultSourceBuilder,
    OperationalDiagnosticsFactory,
    SessionController,
)


def build_controller(
    *, stream: TextIO | None, log_path: Path | None = None
) -> SessionController:
    """Construct a session pipeline identical to the command line's."""

    return SessionController(
        configuration_loader=DefaultConfigurationLoader(),
        scenario_loader=DefaultScenarioLoader(),
        source_builder=DefaultSourceBuilder(),
        runtime_factory=ApplicationRuntimeFactory(),
        diagnostics_factory=OperationalDiagnosticsFactory(stream, log_path=log_path),
    )


def build_desktop_controller() -> SessionController:
    """Build the controller used by the desktop front ends.

    Runtime diagnostics go to stderr and the standard desktop log file, matching
    the command line's behavior so both GUIs report the same session facts.
    """

    return build_controller(stream=sys.stderr, log_path=log_file_path())
