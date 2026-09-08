"""Pure application information for the About screen.

The application version is read from the ``divergencesplitter-ui`` package
metadata, the same authority that builds and distributes the executable. No
second version constant exists anywhere in the UI source.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

APPLICATION_NAME = "DivergenceSplitter"
DISTRIBUTION_NAME = "divergencesplitter-ui"


@dataclass(frozen=True)
class AboutInfo:
    """Transfer-only application identity for the About screen."""

    application_name: str
    version: str


def about_info() -> AboutInfo:
    """Read application identity from the installed package metadata.

    ``metadata.version`` is the injected seam for tests; it is never wrapped
    in a deeper interface hierarchy.
    """

    return AboutInfo(
        application_name=APPLICATION_NAME,
        version=metadata.version(DISTRIBUTION_NAME),
    )
