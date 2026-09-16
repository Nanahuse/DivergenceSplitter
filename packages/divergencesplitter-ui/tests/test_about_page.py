from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import flet as ft
from divergencesplitter_ui.about import VERSION, about_info
from divergencesplitter_ui.about_page import AboutView


def iter_controls(control: ft.Control) -> Iterator[ft.Control]:
    stack = [control]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(getattr(item, "controls", None) or ())
        content = getattr(item, "content", None)
        if isinstance(content, ft.Control):
            stack.append(content)
        title = getattr(item, "title", None)
        if isinstance(title, ft.Control):
            stack.append(title)


def collect_text(control: ft.Control) -> list[str]:
    return [
        item.value
        for item in iter_controls(control)
        if isinstance(item, ft.Text) and isinstance(item.value, str)
    ]


def find_button(control: ft.Control, label: str) -> ft.OutlinedButton:
    for item in iter_controls(control):
        if isinstance(item, ft.OutlinedButton) and item.content == label:
            return item
    raise AssertionError(f"no button labelled {label!r}")


def click(control: ft.OutlinedButton) -> None:
    handler = cast(Callable[[], object] | None, control.on_click)
    assert handler is not None
    handler()


class TestAboutView:
    def test_shows_application_name_and_generated_version(self) -> None:
        view = AboutView()

        texts = collect_text(view.control)
        assert about_info().application_name in texts
        assert f"Version: {VERSION}" in texts

    def test_licenses_round_trip(self) -> None:
        view = AboutView()
        assert view.showing_licenses is False

        click(find_button(view.control, "Licenses..."))
        assert view.showing_licenses is True

        click(find_button(view.control, "Back to About"))
        assert view.showing_licenses is False
