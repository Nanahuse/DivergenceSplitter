"""Flet Licenses view over the bundled static inventory.

The view reads only the bundled ``license_inventory.json`` through the existing
pure ``licenses`` helpers; it never enumerates the installed environment. Each
component is one expandable section, so the long license texts stay collapsed
until requested while the list itself scrolls.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.licenses import (
    bundled_inventory,
    is_packaged_distribution,
    license_sections,
)


class LicenseView:
    """Render the bundled license inventory as expandable sections."""

    def __init__(self) -> None:
        controls: list[ft.Control] = [
            ft.Text("Licenses", size=22),
        ]
        if not is_packaged_distribution():
            controls.append(
                ft.Text(
                    "License information is generated when building the Windows distribution."
                )
            )
        else:
            controls.extend(
                [ft.Text("Select a component to read its license text"), ft.Divider()]
            )
            for section in license_sections(bundled_inventory()):
                controls.append(
                    ft.ExpansionTile(
                        title=ft.Text(section.title),
                        controls=[
                            ft.Container(
                                content=ft.Text(section.text, selectable=True),
                                padding=8,
                            )
                        ],
                        expanded=False,
                        maintain_state=True,
                    )
                )
        self._control = ft.Column(
            controls=controls,
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control
