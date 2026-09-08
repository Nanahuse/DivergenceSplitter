"""Dear PyGui license window backed by the bundled static inventory.

Nothing here resolves distributions, reads the installed environment, or
contacts the network. The package data file generated at release time is the
only source for every name, version, license, and license text shown.
"""

from __future__ import annotations

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.licenses import bundled_inventory, license_sections


class LicensePage:
    """Own the license widgets over the inventory bundled with the UI."""

    PAGE_TAG = "divergence-splitter-licenses-page"

    def build(self, parent: int | str | None = None) -> None:
        """Create the static list once, before the render loop.

        A malformed bundled inventory raises here, failing startup explicitly
        instead of showing an incomplete license list.
        """

        sections = license_sections(bundled_inventory())
        with dpg.group(
            tag=self.PAGE_TAG,
            parent=parent,
            show=False,
        ):
            dpg.add_text("Select a component to read its license text")
            dpg.add_separator()
            for section in sections:
                with dpg.collapsing_header(label=section.title):
                    dpg.add_text(section.text, wrap=400)
