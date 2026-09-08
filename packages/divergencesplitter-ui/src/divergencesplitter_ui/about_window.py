"""Dear PyGui About screen for DivergenceSplitter.

The version shown is read from the ``divergencesplitter-ui`` package metadata,
so the screen never carries a second version authority. The screen also opens
the license window from the bundled static inventory.
"""

from __future__ import annotations

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.about import about_info
from divergencesplitter_ui.license_window import LicenseWindow


class AboutWindow:
    """Own the About widgets and the navigation out to Licenses."""

    WINDOW_TAG = "divergence-splitter-about"

    def __init__(self, license_window: LicenseWindow) -> None:
        self._license_window = license_window

    def build(self) -> None:
        """Create the static widgets once, before the render loop."""

        info = about_info()
        with dpg.window(
            tag=self.WINDOW_TAG,
            label="About DivergenceSplitter",
            width=360,
            height=180,
            show=False,
        ):
            dpg.add_text(info.application_name)
            dpg.add_text(f"Version: {info.version}")
            dpg.add_separator()
            dpg.add_button(label="Licenses...", callback=self._show_licenses)

    def build_main_shortcut(self, parent: int | str) -> None:
        """Add the main-screen shortcut that opens this window."""

        dpg.add_button(
            parent=parent,
            label="About...",
            callback=self._show,
        )

    def _show(self) -> None:
        dpg.show_item(self.WINDOW_TAG)

    def _show_licenses(self) -> None:
        dpg.show_item(self._license_window.WINDOW_TAG)
