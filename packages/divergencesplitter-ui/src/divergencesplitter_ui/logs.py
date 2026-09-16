"""Location of desktop diagnostic log files."""

import sys
from pathlib import Path


def log_file_path() -> Path:
    """Use the executable directory for frozen builds, otherwise the working directory."""
    root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path.cwd()
    )
    return root / "diagnostics.log"


def performance_log_file_path() -> Path:
    """Sibling of the diagnostics log for development-only UI timing records."""
    return log_file_path().with_name("performance.log")
