"""Dear PyGui license window backed by the bundled static inventory.

Nothing here resolves distributions, reads the installed environment, or
contacts the network. The package data file generated at release time is the
only source for every name, version, and license shown.
"""

from __future__ import annotations

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.licenses import bundled_inventory, license_lines


class LicenseWindow:
    """Own the license widgets over the inventory bundled with the UI."""

    WINDOW_TAG = "divergence-splitter-licenses"

    def build(self) -> None:
        """Create the static list once, before the render loop.

        A malformed bundled inventory raises here, failing startup explicitly
        instead of showing an incomplete license list.
        """

        lines = license_lines(bundled_inventory())
        with dpg.window(
            tag=self.WINDOW_TAG,
            label="Licenses",
            width=420,
            height=480,
            show=False,
        ):
            dpg.add_text("Name / Version / License")
            dpg.add_separator()
            for line in lines:
                dpg.add_text(line)
