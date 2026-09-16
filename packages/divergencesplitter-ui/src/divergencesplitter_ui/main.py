"""Command-line entry point for the DivergenceSplitter desktop UI.

This launches the Flet application. An optional configuration path preserves
command-line startup; without one the window opens on the Monitor and a
configuration can be opened from the Configuration page.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from divergencesplitter_ui.bootstrap import build_desktop_controller
from divergencesplitter_ui.flet_application import FletApplication

EXIT_USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="divergencesplitter-ui",
        description="Windows desktop UI for DivergenceSplitter",
    )
    parser.add_argument("configuration", type=Path, nargs="?")
    return parser


def build_application(configuration: Path | None) -> FletApplication:
    """Construct the Flet application with the existing session pipeline."""

    return FletApplication(
        build_desktop_controller(),
        initial_configuration=configuration,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    build_application(arguments.configuration).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
