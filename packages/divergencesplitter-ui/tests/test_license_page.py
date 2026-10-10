from __future__ import annotations

from collections.abc import Iterator

import flet as ft
import pytest
from divergencesplitter_ui import license_page
from divergencesplitter_ui.license_page import LicenseView
from divergencesplitter_ui.licenses import LicenseInventory, license_sections


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


class TestLicenseView:
    def test_builds_one_section_per_inventory_entry(
        self, license_inventory: LicenseInventory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            license_page, "bundled_inventory", lambda: license_inventory
        )
        sections = license_sections(license_inventory)

        view = LicenseView()

        tiles = expansion_tiles(view.control)
        assert [title_text(tile) for tile in tiles] == [s.title for s in sections]

    def test_shows_component_titles_and_license_text(
        self, license_inventory: LicenseInventory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            license_page, "bundled_inventory", lambda: license_inventory
        )
        sections = license_sections(license_inventory)

        view = LicenseView()

        texts = collect_text(view.control)
        assert sections[0].title in texts
        assert any("sample-package" in text for text in texts)
        assert any("MIT License" in text for text in texts)
