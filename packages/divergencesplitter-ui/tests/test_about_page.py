from __future__ import annotations

from collections.abc import Iterator

import flet as ft
from divergencesplitter_ui.about import about_info
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


class TestAboutView:
    def test_shows_application_identity_and_required_links(self) -> None:
        info = about_info()
        view = AboutView()

        texts = collect_text(view.control)
        assert info.application_name in texts
        assert f"Version: {info.version}" in texts

        urls = [
            item.url
            for item in iter_controls(view.control)
            if isinstance(item, ft.TextButton)
        ]
        assert GITHUB_URL in urls
        assert NDI_TRADEMARK_NOTICE in texts
        assert NDI_WEBSITE_URL in urls

    def test_embeds_bundled_licenses(self) -> None:
        sections = license_sections(bundled_inventory())

        view = AboutView()

        texts = collect_text(view.control)
        assert "Licenses" in texts
        assert sections[0].title in texts
