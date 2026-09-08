"""Dear PyGui license window backed by the bundled static inventory.

Nothing here resolves distributions, reads the installed environment, or
contacts the network. The package data file generated at release time is the
only source for every name, version, license, and license text shown.
"""

from __future__ import annotations

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.licenses import bundled_inventory, license_sections


class LicenseWindow:
    """Own the license widgets over the inventory bundled with the UI."""

    WINDOW_TAG = "divergence-splitter-licenses"

    def build(self) -> None:
        """Create the static list once, before the render loop.

        A malformed bundled inventory raises here, failing startup explicitly
        instead of showing an incomplete license list.
        """

        sections = license_sections(bundled_inventory())
        with dpg.window(
            tag=self.WINDOW_TAG,
            label="Licenses",
            width=440,
            height=520,
            show=False,
        ):
            dpg.add_text("Select a component to read its license text")
            dpg.add_separator()
            for section in sections:
                with dpg.collapsing_header(label=section.title):
                    dpg.add_text(section.text, wrap=400)
