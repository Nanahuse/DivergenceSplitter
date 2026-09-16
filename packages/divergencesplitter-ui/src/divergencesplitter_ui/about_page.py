"""Flet About view with its nested Licenses sub-view.

The application name and generated project version come from ``about_info()``.
Licenses is reached from About and returns to About, all inside the same window.
"""

from __future__ import annotations

import flet as ft

from divergencesplitter_ui.about import about_info
from divergencesplitter_ui.license_page import LicenseView


class AboutView:
    """Show application identity and open the nested Licenses view."""

    def __init__(self) -> None:
        info = about_info()
        self._about_section = ft.Column(
            controls=[
                ft.Text(info.application_name, size=22),
                ft.Text(f"Version: {info.version}"),
                ft.Divider(),
                ft.OutlinedButton(
                    content="Licenses...",
                    on_click=self._show_licenses,
                ),
            ],
            spacing=8,
        )
        self._license_view = LicenseView(on_back=self.show_about)
        self._license_section = ft.Container(
            content=self._license_view.control,
            visible=False,
            expand=True,
        )
        self._control = ft.Column(
            controls=[self._about_section, self._license_section],
            spacing=8,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def showing_licenses(self) -> bool:
        return self._license_section.visible

    def show_about(self) -> None:
        self._about_section.visible = True
        self._license_section.visible = False
        self._request_update()

    def _show_licenses(self, event: ft.Event[ft.OutlinedButton] | None = None) -> None:
        self._about_section.visible = False
        self._license_section.visible = True
        self._request_update()

    def _request_update(self) -> None:
        try:
            self._control.update()
        except RuntimeError:
            pass
