from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import flet as ft
from divergencesplitter_ui.license_page import LicenseView
from divergencesplitter_ui.licenses import bundled_inventory, license_sections


def iter_controls(control: ft.Control) -> Iterator[ft.Control]:
    """Yield controls in document order so sibling order is preserved."""

    yield control
    for child in getattr(control, "controls", None) or ():
        yield from iter_controls(child)
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from iter_controls(content)
    title = getattr(control, "title", None)
    if isinstance(title, ft.Control):
        yield from iter_controls(title)
    for action in getattr(control, "actions", None) or ():
        yield from iter_controls(action)


def collect_text(control: ft.Control) -> list[str]:
    return [
        item.value
        for item in iter_controls(control)
        if isinstance(item, ft.Text) and isinstance(item.value, str)
    ]


def expansion_tiles(control: ft.Control) -> list[ft.ExpansionTile]:
    return [
        item for item in iter_controls(control) if isinstance(item, ft.ExpansionTile)
    ]


def title_text(tile: ft.ExpansionTile) -> str:
    title = tile.title
    if isinstance(title, str):
        return title
    return str(getattr(title, "value", ""))


def find_button(control: ft.Control, label: str) -> ft.OutlinedButton:
    for item in iter_controls(control):
        if isinstance(item, ft.OutlinedButton) and item.content == label:
            return item
    raise AssertionError(f"no button labelled {label!r}")


def click(control: ft.OutlinedButton) -> None:
    handler = cast(Callable[[], object] | None, control.on_click)
    assert handler is not None
    handler()


class TestLicenseView:
    def test_builds_one_section_per_inventory_entry(self) -> None:
        sections = license_sections(bundled_inventory())

        view = LicenseView()

        tiles = expansion_tiles(view.control)
        assert [title_text(tile) for tile in tiles] == [s.title for s in sections]

    def test_shows_component_titles_and_license_text(self) -> None:
        sections = license_sections(bundled_inventory())

        view = LicenseView()

        texts = collect_text(view.control)
        assert sections[0].title in texts
        assert any("numpy" in text for text in texts)
        assert any("GNU GENERAL PUBLIC LICENSE" in text for text in texts)

    def test_body_is_scrollable(self) -> None:
        view = LicenseView()

        assert cast(ft.Column, view.control).scroll == ft.ScrollMode.AUTO

    def test_back_button_invokes_callback(self) -> None:
        calls: list[bool] = []
        view = LicenseView(on_back=lambda: calls.append(True))

        click(find_button(view.control, "Back to About"))

        assert calls == [True]

    def test_without_back_callback_has_no_button(self) -> None:
        view = LicenseView()

        labels = [
            item.content
            for item in iter_controls(view.control)
            if isinstance(item, ft.OutlinedButton)
        ]
        assert "Back to About" not in labels
