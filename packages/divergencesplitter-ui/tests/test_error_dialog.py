from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import flet as ft
from divergencesplitter_ui.error_dialog import ErrorDialog
from divergencesplitter_ui.session import (
    SessionFailureKind,
    SessionResult,
    SessionState,
)


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
        stack.extend(getattr(item, "actions", None) or ())


def collect_text(control: ft.Control) -> list[str]:
    return [
        item.value
        for item in iter_controls(control)
        if isinstance(item, ft.Text) and isinstance(item.value, str)
    ]


def find_button(control: ft.Control, label: str) -> ft.TextButton:
    for item in iter_controls(control):
        if isinstance(item, ft.TextButton) and item.content == label:
            return item
    raise AssertionError(f"no text button labelled {label!r}")


def click(control: ft.TextButton) -> None:
    handler = cast(Callable[[], object] | None, control.on_click)
    assert handler is not None
    handler()


def failure(message: str = "boom") -> SessionResult:
    return SessionResult(
        SessionState.FAILED,
        RuntimeError(message),
        SessionFailureKind.RUNTIME,
    )


def make_dialog() -> tuple[ErrorDialog, list[ft.AlertDialog], list[bool]]:
    shown: list[ft.AlertDialog] = []
    hidden: list[bool] = []
    dialog = ErrorDialog(
        show_dialog=lambda view: shown.append(view),
        hide_dialog=lambda: hidden.append(True),
    )
    return dialog, shown, hidden


class TestErrorDialog:
    def test_failure_is_rendered_and_shown(self) -> None:
        dialog, shown, _ = make_dialog()

        assert dialog.tick(failure()) is True

        assert len(shown) == 1
        texts = collect_text(shown[0])
        assert any("Runtime" in text for text in texts)
        assert any("RuntimeError" in text for text in texts)
        assert any("boom" in text for text in texts)

    def test_close_hides_dialog(self) -> None:
        dialog, shown, hidden = make_dialog()
        dialog.tick(failure())

        click(find_button(shown[0], "Close"))

        assert hidden == [True]

    def test_dismiss_hides_dialog(self) -> None:
        dialog, shown, hidden = make_dialog()
        dialog.tick(failure())

        dismissed = cast(Callable[[], object] | None, shown[0].on_dismiss)
        assert dismissed is not None
        dismissed()

        assert hidden == [True]
