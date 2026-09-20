"""Vertical navigation for the Flet application layout.

The navigation is one column on the left of the window. Everyday views sit at
the top (Monitor, Diagnostics, Profile), while the rarely used application
management and information views (Settings, About) are pushed to the bottom by
an expanding spacer. It only reports the selected view; switching views never
stops or restarts the runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

import flet as ft

NAVIGATION_WIDTH = 180


class AppView(StrEnum):
    """The top-level page the navigation is showing."""

    MONITOR = "monitor"
    DIAGNOSTICS = "diagnostics"
    PROFILE = "profile"
    SETTINGS = "settings"
    ABOUT = "about"


TOP_VIEWS = (AppView.MONITOR, AppView.DIAGNOSTICS, AppView.PROFILE)
BOTTOM_VIEWS = (AppView.SETTINGS, AppView.ABOUT)

_LABELS = {
    AppView.MONITOR: "Monitor",
    AppView.DIAGNOSTICS: "Diagnostics",
    AppView.PROFILE: "Profile",
    AppView.SETTINGS: "Settings",
    AppView.ABOUT: "About",
}
_ICONS = {
    AppView.MONITOR: ft.Icons.MONITOR,
    AppView.DIAGNOSTICS: ft.Icons.TROUBLESHOOT,
    AppView.PROFILE: ft.Icons.PERSON,
    AppView.SETTINGS: ft.Icons.SETTINGS,
    AppView.ABOUT: ft.Icons.INFO,
}


class Navigation:
    """Render the left navigation and report view selection."""

    def __init__(
        self,
        *,
        on_select: Callable[[AppView], None],
        selected: AppView = AppView.MONITOR,
    ) -> None:
        self._on_select = on_select
        self._selected = selected
        self._items: dict[AppView, ft.Container] = {}
        self._spacer = ft.Container(expand=True)
        self._control = ft.Container(
            content=ft.Column(
                controls=[
                    *(self._build_item(view) for view in TOP_VIEWS),
                    self._spacer,
                    *(self._build_item(view) for view in BOTTOM_VIEWS),
                ],
                spacing=4,
                expand=True,
            ),
            width=NAVIGATION_WIDTH,
            padding=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self._apply_selection()

    @property
    def control(self) -> ft.Container:
        return self._control

    @property
    def spacer(self) -> ft.Container:
        """The expanding spacer separating the top and bottom groups."""

        return self._spacer

    @property
    def selected(self) -> AppView:
        return self._selected

    @property
    def items(self) -> dict[AppView, ft.Container]:
        return self._items

    def select(self, view: AppView, *, notify: bool = False) -> None:
        """Reflect a selection made elsewhere, optionally reporting it."""

        self._selected = view
        self._apply_selection()
        if notify:
            self._on_select(view)

    def _build_item(self, view: AppView) -> ft.Container:
        container = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(_ICONS[view], size=20),
                    ft.Text(_LABELS[view], size=14),
                ],
                spacing=12,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=8,
            on_click=lambda event, view=view: self.select(view, notify=True),
        )
        self._items[view] = container
        return container

    def _apply_selection(self) -> None:
        for view, container in self._items.items():
            selected = view is self._selected
            container.bgcolor = (
                ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY) if selected else None
            )
            row = container.content
            assert isinstance(row, ft.Row)
            icon, label = row.controls
            assert isinstance(icon, ft.Icon)
            assert isinstance(label, ft.Text)
            color = ft.Colors.PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT
            icon.color = color
            label.color = color
            label.weight = ft.FontWeight.BOLD if selected else ft.FontWeight.NORMAL


__all__ = ["BOTTOM_VIEWS", "NAVIGATION_WIDTH", "TOP_VIEWS", "AppView", "Navigation"]
