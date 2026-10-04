"""Location of desktop diagnostic log files."""

from pathlib import Path

from divergencesplitter_runtime.configuration.application_data import (
    application_data_directory,
)


def log_file_path() -> Path:
    """Return the fixed per-user diagnostic log file location."""

    return application_data_directory() / "diagnostics.log"
