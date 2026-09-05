"""Command-line entry point for the Windows-only desktop UI.

The configuration path is accepted as the single positional argument so the UI
can start before 9.3c's settings screen exists. No explicit start button is
added; starting a session is driven by the boundary argument.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from divergencesplitter_ui.application import run_configuration

EXIT_USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="divergencesplitter-ui",
        description="Windows desktop UI for DivergenceSplitter",
    )
    parser.add_argument("configuration", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    run_configuration(arguments.configuration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
