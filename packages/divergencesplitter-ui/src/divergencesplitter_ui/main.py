"""Command-line entry point for the DivergenceSplitter desktop UI.

This launches the Flet application. An optional Profile path preserves
command-line startup; without one the window opens on the Monitor and the last
used Profile (or none) is restored from App Settings.
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
    parser.add_argument("profile", type=Path, nargs="?")
    return parser


def build_application(profile: Path | None) -> FletApplication:
    """Construct the Flet application with the existing session pipeline."""

    return FletApplication(
        build_desktop_controller(),
        initial_profile=profile,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    build_application(arguments.profile).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
