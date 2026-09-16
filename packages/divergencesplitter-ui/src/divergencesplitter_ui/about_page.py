"""Flet About view with the embedded Licenses list.

The application name and version come from the existing pure ``about_info()``
(authority: the generated ``_version`` module), so no version is hardcoded here.
The bundled license inventory is part of the page itself: opening About shows
the license tree directly instead of switching to a separate view.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.about import about_info
from divergencesplitter_ui.license_page import LicenseView


class AboutView:
    """Show application identity together with the bundled license tree."""

    def __init__(self) -> None:
        info = about_info()
        self._license_view = LicenseView()
        self._control = ft.Column(
            controls=[
                ft.Text(info.application_name, size=22),
                ft.Text(f"Version: {info.version}"),
                ft.Divider(),
                self._license_view.control,
            ],
            spacing=8,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control
