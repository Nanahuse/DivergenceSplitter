"""Vertical navigation for the Flet application layout.

The navigation is one column on the left of the window. Everyday views sit at
the top (Monitor, Diagnostics, Profile), while the rarely used application
management and information views (Settings, About) are pushed to the bottom by
an expanding spacer. It only reports the selected view; switching views never
stops or restarts the runtime.

The bar starts collapsed: it shows icons only and stays narrow so the main
content gets more room. A dedicated chevron button at the top toggles the
expanded, label-bearing layout. The expand state is a transient display concern
owned by this component: it is independent of the selected view and is never
persisted, so a restart always starts collapsed.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

import flet as ft

COLLAPSED_NAVIGATION_WIDTH = 60
EXPANDED_NAVIGATION_WIDTH = 180

_EXPAND_TOOLTIP = "Expand navigation"
_COLLAPSE_TOOLTIP = "Collapse navigation"


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
    AppView.PROFILE: ft.Icons.DESCRIPTION,
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
        # Collapsed is the only startup state; selection and expansion are
        # tracked separately so toggling never changes the selected view.
        self._expanded = False
        self._items: dict[AppView, ft.Container] = {}
        self._labels: dict[AppView, ft.Text] = {}
        self._spacer = ft.Container(expand=True)
        self._toggle_icon = ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20)
        self._toggle = ft.Container(
            content=self._toggle_icon,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=8,
            on_click=self.toggle_expanded,
            key="nav-toggle",
        )
        self._control = ft.Container(
            content=ft.Column(
                controls=[
                    self._toggle,
                    *(self._build_item(view) for view in TOP_VIEWS),
                    self._spacer,
                    *(self._build_item(view) for view in BOTTOM_VIEWS),
                ],
                spacing=4,
                expand=True,
            ),
            padding=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self._apply_selection()
        self._apply_expanded()

    @property
    def control(self) -> ft.Container:
        return self._control

    @property
    def spacer(self) -> ft.Container:
        """The expanding spacer separating the top and bottom groups."""

        return self._spacer

    @property
    def toggle(self) -> ft.Container:
        """The chevron button that expands and collapses the bar."""

        return self._toggle

    @property
    def selected(self) -> AppView:
        return self._selected

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def items(self) -> dict[AppView, ft.Container]:
        return self._items

    def select(self, view: AppView, *, notify: bool = False) -> None:
        """Reflect a selection made elsewhere, optionally reporting it."""

        self._selected = view
        self._apply_selection()
        if notify:
            self._on_select(view)

    def toggle_expanded(self, event: ft.Event[ft.Container] | None = None) -> None:
        """Flip between the collapsed and expanded layouts.

        This is a display-only change: the selected view is left untouched.
        """

        self._expanded = not self._expanded
        self._apply_expanded()
        try:
            self._control.update()
        except RuntimeError:
            # Not mounted on a page yet; nothing to repaint.
            pass

    def _build_item(self, view: AppView) -> ft.Container:
        icon = ft.Icon(_ICONS[view], size=20)
        label = ft.Text(_LABELS[view], size=14)
        container = ft.Container(
            content=ft.Row(controls=[icon, label], spacing=12),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=8,
            on_click=lambda event, view=view: self.select(view, notify=True),
            key=f"nav-{view.value}",
        )
        self._items[view] = container
        self._labels[view] = label
        return container

    def _apply_expanded(self) -> None:
        self._control.width = (
            EXPANDED_NAVIGATION_WIDTH if self._expanded else COLLAPSED_NAVIGATION_WIDTH
        )
        self._toggle_icon.icon = (
            ft.Icons.CHEVRON_LEFT if self._expanded else ft.Icons.CHEVRON_RIGHT
        )
        self._toggle.tooltip = _COLLAPSE_TOOLTIP if self._expanded else _EXPAND_TOOLTIP
        for view, label in self._labels.items():
            label.visible = self._expanded
            self._items[view].tooltip = None if self._expanded else _LABELS[view]

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


__all__ = [
    "BOTTOM_VIEWS",
    "COLLAPSED_NAVIGATION_WIDTH",
    "EXPANDED_NAVIGATION_WIDTH",
    "TOP_VIEWS",
    "AppView",
    "Navigation",
]
