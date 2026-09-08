"""Dear PyGui About screen for DivergenceSplitter.

The version shown is read from the ``divergencesplitter-ui`` package metadata,
so the screen never carries a second version authority. The screen also opens
the license window from the bundled static inventory.
"""

from __future__ import annotations

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.about import about_info
from divergencesplitter_ui.license_window import LicensePage


class AboutPage:
    """Own the About page and the navigation out to Licenses."""

    PAGE_TAG = "divergence-splitter-about-page"

    def __init__(self, license_window: LicensePage) -> None:
        self._license_window = license_window

    def build(self, parent: int | str | None = None) -> None:
        """Create the static widgets once, before the render loop."""

        info = about_info()
        with dpg.group(parent=parent):
            dpg.add_text(info.application_name)
            dpg.add_text(f"Version: {info.version}")
            dpg.add_separator()
            dpg.add_button(label="Licenses...", callback=self._show_licenses)

    def _show_licenses(self) -> None:
        dpg.hide_item(self.PAGE_TAG)
        dpg.show_item(self._license_window.PAGE_TAG)
