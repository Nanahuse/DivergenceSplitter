"""Flet About view with the repository link and embedded Licenses list.

The application name and version come from the existing pure ``about_info()``
(authority: the generated ``_version`` module), so no version is hardcoded here.
The bundled license inventory is part of the page itself: opening About shows
the license tree directly instead of switching to a separate view. The GitHub
link is a quiet text button rather than a primary action.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.about import about_info
from divergencesplitter_ui.license_page import LicenseView
from divergencesplitter_ui.ndi_branding import NDI_TRADEMARK_NOTICE, NDI_WEBSITE_URL

GITHUB_URL = "https://github.com/Nanahuse/DivergenceSplitter"


class AboutView:
    """Show application identity together with the bundled license tree."""

    def __init__(self) -> None:
        info = about_info()
        self._license_view = LicenseView()
        self._github_button = ft.TextButton(content="GitHub ↗", url=GITHUB_URL)
        self._ndi_button = ft.TextButton(content="NDI website ↗", url=NDI_WEBSITE_URL)
        self._control = ft.Column(
            controls=[
                ft.Text(info.application_name, size=22),
                ft.Text(f"Version: {info.version}"),
                ft.Container(height=4),
                self._github_button,
                self._ndi_button,
                ft.Text(NDI_TRADEMARK_NOTICE, size=11),
                ft.Divider(),
                self._license_view.control,
            ],
            spacing=8,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def github_button(self) -> ft.TextButton:
        return self._github_button

    @property
    def ndi_button(self) -> ft.TextButton:
        return self._ndi_button
