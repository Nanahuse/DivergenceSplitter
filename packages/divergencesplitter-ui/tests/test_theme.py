from __future__ import annotations

from typing import cast

import flet as ft
import pytest
from divergencesplitter_runtime.configuration.models import Theme
from divergencesplitter_runtime.instance_runtime import InstanceRuntimeState
from divergencesplitter_ui.theme import (
    DARK_ACTIVE,
    DARK_ERROR,
    DARK_INACTIVE,
    DARK_PRIMARY,
    DARK_WARNING,
    apply_theme,
    dark_theme,
    instance_status_color,
    semantic_colors,
)


class FakePage:
    def __init__(self) -> None:
        self.theme = "unset"
        self.dark_theme = "unset"
        self.theme_mode = None


class TestApplyTheme:
    def test_light_keeps_the_standard_light_theme(self) -> None:
        page = FakePage()

        apply_theme(cast(ft.Page, page), Theme.LIGHT)

        assert page.theme is None
        assert page.theme_mode is ft.ThemeMode.LIGHT

    def test_dark_installs_the_dedicated_theme(self) -> None:
        page = FakePage()

        apply_theme(cast(ft.Page, page), Theme.DARK)

        assert page.theme_mode is ft.ThemeMode.DARK
        assert page.theme is None
        assert isinstance(page.dark_theme, ft.Theme)

    def test_dark_theme_uses_the_palette(self) -> None:
        theme = dark_theme()

        assert theme.color_scheme is not None
        assert theme.color_scheme.primary == DARK_PRIMARY
        assert theme.color_scheme.on_primary == "#251207"
        assert theme.color_scheme.surface == "#1A201B"
        assert theme.scaffold_bgcolor == "#111512"
        assert theme.card_bgcolor == "#1A201B"
        assert theme.divider_color == "#354039"

    def test_dark_navigation_rail_theme(self) -> None:
        rail = dark_theme().navigation_rail_theme

        assert rail is not None
        assert rail.bgcolor == "#0B0E0C"
        assert rail.indicator_color == "#4D2B18"
        assert rail.selected_label_text_style is not None
        assert rail.selected_label_text_style.color == DARK_PRIMARY


class TestSemanticColors:
    def test_dark_roles_match_the_palette(self) -> None:
        colors = semantic_colors(Theme.DARK)

        assert colors.active == DARK_ACTIVE
        assert colors.ready == DARK_ACTIVE
        assert colors.connecting == DARK_WARNING
        assert colors.failed == DARK_ERROR
        assert colors.stopped == DARK_INACTIVE
        assert colors.error == DARK_ERROR
        assert colors.primary == DARK_PRIMARY

    def test_light_roles_keep_the_standard_appearance(self) -> None:
        colors = semantic_colors(Theme.LIGHT)

        assert colors.ready == ft.Colors.GREEN_400
        assert colors.connecting == ft.Colors.AMBER_400
        assert colors.failed == ft.Colors.RED_400
        assert colors.stopped == ft.Colors.GREY_500
        assert colors.active == ft.Colors.AMBER

    @pytest.mark.parametrize(
        ("state", "role"),
        [
            (InstanceRuntimeState.READY, "ready"),
            (InstanceRuntimeState.CONNECTING, "connecting"),
            (InstanceRuntimeState.FAILED, "failed"),
            (InstanceRuntimeState.STOPPED, "stopped"),
        ],
    )
    def test_instance_status_color_maps_each_state(
        self, state: InstanceRuntimeState, role: str
    ) -> None:
        colors = semantic_colors(Theme.DARK)

        assert instance_status_color(state, colors) == getattr(colors, role)

    def test_instance_status_color_is_none_for_unknown_state(self) -> None:
        colors = semantic_colors(Theme.LIGHT)

        assert instance_status_color(None, colors) is None
