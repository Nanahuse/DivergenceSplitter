"""Pure application information for the About screen.

The application version is generated into ``_version.py`` from
``packages/divergencesplitter-ui/pyproject.toml`` by
``tools/generate_ui_version.py``. That file is the single authority for the
version; the Flet bundle does not expose installed distribution metadata, so
``importlib.metadata`` is not used here.
"""

from __future__ import annotations

from dataclasses import dataclass

from divergencesplitter_ui._version import VERSION

APPLICATION_NAME = "DivergenceSplitter"


@dataclass(frozen=True)
class AboutInfo:
    """Transfer-only application identity for the About screen."""

    application_name: str
    version: str


def about_info() -> AboutInfo:
    """Return application identity using the generated project version."""

    return AboutInfo(
        application_name=APPLICATION_NAME,
        version=VERSION,
    )
