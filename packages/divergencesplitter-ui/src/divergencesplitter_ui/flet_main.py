"""Command-line entry point for the Flet Monitor.

This is a temporary parallel entry point while the Dear PyGui UI remains the
default ``divergencesplitter-ui``. It accepts the same optional configuration
path: when supplied, the session starts after the window opens; otherwise the
Monitor shows the idle state.
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
        prog="divergencesplitter-ui-flet",
        description="Flet Monitor for DivergenceSplitter",
    )
    parser.add_argument("configuration", type=Path, nargs="?")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    application = FletApplication(
        build_desktop_controller(),
        initial_configuration=arguments.configuration,
    )
    application.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
