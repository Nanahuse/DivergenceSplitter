"""Command-line entry point for the Windows-only desktop UI.

An optional configuration path preserves command-line startup while the
settings screen can open a configuration when no path is supplied. No explicit
start button is added; opening or saving a valid configuration starts a session.
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
    parser.add_argument("configuration", type=Path, nargs="?")
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
