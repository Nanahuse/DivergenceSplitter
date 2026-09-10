"""Bundled Japanese-capable default font for the Dear PyGui UI.

The application ships ``Noto Sans JP`` so Japanese paths and other Unicode
strings render the same on every Windows machine without depending on a font
installed on the operating system. The font is registered once per process and
bound as Dear PyGui's global font, so every widget and every future UI string
uses it without any per-widget font binding.

``importlib.resources`` resolves the bundled font from a source checkout, an
installed wheel, and a PyInstaller bundle alike. A missing font is a broken
distribution, so it fails with an explicit error instead of silently falling
back to an operating-system font.
"""

from __future__ import annotations

import importlib.resources
from importlib.resources.abc import Traversable

PACKAGE = "divergencesplitter_ui"
FONT_RESOURCE = "assets/fonts/NotoSansJP[wght].ttf"
FONT_LICENSE_RESOURCE = "assets/fonts/OFL.txt"
DEFAULT_FONT_SIZE = 16


class BundledFontError(RuntimeError):
    """A font asset that must ship with the UI is missing or broken."""


def font_resource() -> Traversable:
    """Return the bundled Noto Sans JP font as a package resource."""

    return importlib.resources.files(PACKAGE).joinpath(FONT_RESOURCE)


def font_license_resource() -> Traversable:
    """Return the SIL Open Font License shipped alongside the font."""

    return importlib.resources.files(PACKAGE).joinpath(FONT_LICENSE_RESOURCE)


def configure_default_font() -> None:
    """Register Noto Sans JP and bind it as Dear PyGui's global font.

    This must run after ``dearpygui.create_context`` and before any widget is
    created, so every widget in the application inherits the bundled font.
    """

    from divergencesplitter_ui._dpg import dpg

    resource = font_resource()
    if not resource.is_file():
        raise BundledFontError(f"bundled font is missing: {FONT_RESOURCE}")
    with importlib.resources.as_file(resource) as path, dpg.font_registry():
        font = dpg.add_font(str(path), DEFAULT_FONT_SIZE)
    dpg.bind_font(font)
