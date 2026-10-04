"""Per-user application data directory shared by settings and diagnostics.

The location is resolved in one place so App Settings and the diagnostic log
never disagree. It never depends on the current working directory or on the
running executable, so a source checkout and a frozen build share one directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APPLICATION_DIRECTORY = "DivergenceSplitter"


def application_data_directory() -> Path:
    """Return the per-user directory that stores DivergenceSplitter data.

    Windows uses ``%APPDATA%\\DivergenceSplitter`` (falling back to
    ``%USERPROFILE%\\AppData\\Roaming``); other platforms use
    ``$XDG_CONFIG_HOME/DivergenceSplitter`` (falling back to
    ``~/.config/DivergenceSplitter``).
    """

    return _application_data_root(os.name, os.environ)


def _application_data_root(platform: str, environ: Mapping[str, str]) -> Path:
    if platform == "nt":
        base = environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / APPLICATION_DIRECTORY
