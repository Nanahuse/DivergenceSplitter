"""Application information for the About screen.

The application version is generated from the UI package's ``pyproject.toml``.
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
