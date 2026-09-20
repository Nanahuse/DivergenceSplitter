from __future__ import annotations

from collections.abc import Iterator

import flet as ft
from divergencesplitter_ui.about import VERSION, about_info
from divergencesplitter_ui.about_page import GITHUB_URL, AboutView
from divergencesplitter_ui.licenses import bundled_inventory, license_sections
from divergencesplitter_ui.ndi_branding import NDI_TRADEMARK_NOTICE, NDI_WEBSITE_URL


def iter_controls(control: ft.Control) -> Iterator[ft.Control]:
    yield control
    for child in getattr(control, "controls", None) or ():
        yield from iter_controls(child)
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from iter_controls(content)
    title = getattr(control, "title", None)
    if isinstance(title, ft.Control):
        yield from iter_controls(title)


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


class TestAboutView:
    def test_shows_application_name_and_generated_version(self) -> None:
        view = AboutView()

        texts = collect_text(view.control)
        assert about_info().application_name in texts
        assert f"Version: {VERSION}" in texts

    def test_shows_license_tree_immediately(self) -> None:
        sections = license_sections(bundled_inventory())

        view = AboutView()

        texts = collect_text(view.control)
        assert "Licenses" in texts
        assert sections[0].title in texts
        assert [title_text(tile) for tile in expansion_tiles(view.control)] == [
            section.title for section in sections
        ]

    def test_has_no_license_navigation(self) -> None:
        view = AboutView()

        labels = [
            item.content
            for item in iter_controls(view.control)
            if isinstance(item, ft.OutlinedButton)
        ]
        assert "Licenses..." not in labels
        assert "Back to About" not in labels

    def test_links_to_the_github_repository(self) -> None:
        view = AboutView()

        urls = [
            item.url
            for item in iter_controls(view.control)
            if isinstance(item, ft.TextButton)
        ]
        assert GITHUB_URL in urls
        assert GITHUB_URL == "https://github.com/Nanahuse/DivergenceSplitter"

    def test_shows_ndi_trademark_and_website_link(self) -> None:
        view = AboutView()

        texts = collect_text(view.control)
        assert NDI_TRADEMARK_NOTICE in texts

        urls = [
            item.url
            for item in iter_controls(view.control)
            if isinstance(item, ft.TextButton)
        ]
        assert NDI_WEBSITE_URL in urls
        assert NDI_WEBSITE_URL == "https://ndi.video/"
