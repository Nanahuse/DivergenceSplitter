"""Application theme definitions and semantic status colors.

The application never follows the OS theme. :data:`Theme.LIGHT` keeps Flet's
standard light appearance, while :data:`Theme.DARK` installs the dedicated
DivergenceSplitter palette below. Panels never hard-code a state color: they ask
:func:`semantic_colors` for the role that matches the current theme, so the same
status has one meaning in every theme.
"""

from __future__ import annotations

from dataclasses import dataclass

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme
from divergencesplitter_runtime.instance_runtime import InstanceRuntimeState

# Dedicated Dark palette.
DARK_BACKGROUND = "#111512"
DARK_DEEP_BACKGROUND = "#0B0E0C"
DARK_SURFACE_LOW = "#151A16"
DARK_SURFACE = "#1A201B"
DARK_SURFACE_HIGH = "#212921"
DARK_SURFACE_HIGHEST = "#29332A"
DARK_DIVIDER = "#354039"
DARK_OUTLINE = "#5E6A60"
DARK_PRIMARY = "#F08A35"
DARK_PRIMARY_CONTAINER = "#4D2B18"
DARK_ON_PRIMARY = "#251207"
DARK_TEXT_PRIMARY = "#E7E1D3"
DARK_TEXT_SECONDARY = "#B4B2A8"
DARK_ACTIVE = "#78C99A"
DARK_WARNING = "#D4AD54"
DARK_ERROR = "#E06B64"
DARK_INACTIVE = "#7D8981"


@dataclass(frozen=True)
class SemanticColors:
    """Theme-invariant roles resolved to concrete colors for one theme.

    ``active``/``ready`` mean the system is evaluating or running, ``connecting``
    and ``warning`` share the caution color, ``failed``/``error`` the failure
    color, and ``stopped`` the inactive color. ``primary`` marks user selection
    and primary actions, never a runtime success state.
    """

    active: str
    ready: str
    connecting: str
    failed: str
    stopped: str
    error: str
    warning: str
    primary: str
    on_primary: str
    muted: str


LIGHT_SEMANTIC_COLORS = SemanticColors(
    active=ft.Colors.AMBER,
    ready=ft.Colors.GREEN_400,
    connecting=ft.Colors.AMBER_400,
    failed=ft.Colors.RED_400,
    stopped=ft.Colors.GREY_500,
    error=ft.Colors.RED_400,
    warning=ft.Colors.AMBER_400,
    primary=ft.Colors.ORANGE_300,
    on_primary=ft.Colors.WHITE,
    muted=ft.Colors.GREY_500,
)

DARK_SEMANTIC_COLORS = SemanticColors(
    active=DARK_ACTIVE,
    ready=DARK_ACTIVE,
    connecting=DARK_WARNING,
    failed=DARK_ERROR,
    stopped=DARK_INACTIVE,
    error=DARK_ERROR,
    warning=DARK_WARNING,
    primary=DARK_PRIMARY,
    on_primary=DARK_ON_PRIMARY,
    muted=DARK_INACTIVE,
)

_STATUS_ROLES = {
    InstanceRuntimeState.READY: "ready",
    InstanceRuntimeState.CONNECTING: "connecting",
    InstanceRuntimeState.FAILED: "failed",
    InstanceRuntimeState.STOPPED: "stopped",
}


def semantic_colors(theme: Theme) -> SemanticColors:
    """Return the semantic status colors for one theme."""

    return DARK_SEMANTIC_COLORS if theme is Theme.DARK else LIGHT_SEMANTIC_COLORS


def instance_status_color(
    state: InstanceRuntimeState | None,
    colors: SemanticColors,
) -> str | None:
    """Resolve one instance runtime state to its semantic role color."""

    role = _STATUS_ROLES.get(state)
    return None if role is None else getattr(colors, role)


def dark_theme() -> ft.Theme:
    """Build the dedicated DivergenceSplitter dark theme."""

    scheme = ft.ColorScheme(
        primary=DARK_PRIMARY,
        on_primary=DARK_ON_PRIMARY,
        primary_container=DARK_PRIMARY_CONTAINER,
        on_primary_container=DARK_PRIMARY,
        secondary=DARK_ACTIVE,
        on_secondary=DARK_DEEP_BACKGROUND,
        secondary_container=DARK_PRIMARY_CONTAINER,
        on_secondary_container=DARK_PRIMARY,
        tertiary=DARK_ACTIVE,
        on_tertiary=DARK_DEEP_BACKGROUND,
        tertiary_container=DARK_PRIMARY_CONTAINER,
        on_tertiary_container=DARK_ACTIVE,
        error=DARK_ERROR,
        on_error=DARK_ON_PRIMARY,
        error_container=DARK_PRIMARY_CONTAINER,
        on_error_container=DARK_ERROR,
        surface=DARK_SURFACE,
        on_surface=DARK_TEXT_PRIMARY,
        on_surface_variant=DARK_TEXT_SECONDARY,
        outline=DARK_OUTLINE,
        outline_variant=DARK_DIVIDER,
        shadow="#000000",
        scrim="#000000",
        inverse_surface=DARK_TEXT_PRIMARY,
        on_inverse_surface=DARK_ON_PRIMARY,
        inverse_primary=DARK_PRIMARY,
        surface_tint=DARK_PRIMARY,
        surface_dim=DARK_DEEP_BACKGROUND,
        surface_bright=DARK_SURFACE_HIGHEST,
        surface_container_lowest=DARK_DEEP_BACKGROUND,
        surface_container_low=DARK_SURFACE_LOW,
        surface_container=DARK_SURFACE,
        surface_container_high=DARK_SURFACE_HIGH,
        surface_container_highest=DARK_SURFACE_HIGHEST,
    )
    return ft.Theme(
        color_scheme=scheme,
        scaffold_bgcolor=DARK_BACKGROUND,
        card_bgcolor=DARK_SURFACE,
        divider_color=DARK_DIVIDER,
        hint_color=DARK_INACTIVE,
        navigation_rail_theme=ft.NavigationRailTheme(
            bgcolor=DARK_DEEP_BACKGROUND,
            indicator_color=DARK_PRIMARY_CONTAINER,
            selected_label_text_style=ft.TextStyle(color=DARK_PRIMARY),
            unselected_label_text_style=ft.TextStyle(color=DARK_TEXT_SECONDARY),
        ),
    )


def apply_theme(page: ft.Page, theme: Theme) -> None:
    """Apply one theme to the page.

    Light keeps Flet's standard light theme (``page.theme`` stays ``None``);
    Dark installs the dedicated :func:`dark_theme`.
    """

    page.theme_mode = ft.ThemeMode.DARK if theme is Theme.DARK else ft.ThemeMode.LIGHT
    page.theme = None
    page.dark_theme = dark_theme()
