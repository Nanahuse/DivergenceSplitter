from __future__ import annotations

from collections.abc import Callable, Iterator
from importlib import metadata
from typing import cast

import flet as ft
import pytest
from divergencesplitter_ui.about import about_info
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
    def test_shows_application_name_and_metadata_version(self, monkeypatch) -> None:
        monkeypatch.setattr(metadata, "version", lambda name: "9.9.9")

        view = AboutView()

        texts = collect_text(view.control)
        assert about_info().application_name in texts
        assert "Version: 9.9.9" in texts

    def test_version_is_not_hardcoded(self, monkeypatch) -> None:
        monkeypatch.setattr(metadata, "version", lambda name: "4.5.6")

        view = AboutView()

        assert any("4.5.6" in text for text in collect_text(view.control))

    def test_licenses_round_trip(self, monkeypatch) -> None:
        monkeypatch.setattr(metadata, "version", lambda name: "1.2.3")
        view = AboutView()
        assert view.showing_licenses is False

        click(find_button(view.control, "Licenses..."))
        assert view.showing_licenses is True

        click(find_button(view.control, "Back to About"))
        assert view.showing_licenses is False

    def test_missing_metadata_is_reported(self, monkeypatch) -> None:
        def missing(name: str) -> str:
            raise metadata.PackageNotFoundError(name)

        monkeypatch.setattr(metadata, "version", missing)

        with pytest.raises(metadata.PackageNotFoundError):
            AboutView()
