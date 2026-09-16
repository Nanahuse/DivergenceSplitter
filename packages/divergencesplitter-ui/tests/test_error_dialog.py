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
    def test_no_result_shows_nothing(self) -> None:
        dialog, shown, _ = make_dialog()

        assert dialog.tick(None) is False
        assert shown == []

    def test_terminal_failure_shows_category_type_and_message(self) -> None:
        dialog, shown, _ = make_dialog()

        assert dialog.tick(failure()) is True

        assert len(shown) == 1
        texts = collect_text(shown[0])
        assert any("Runtime" in text for text in texts)
        assert any("RuntimeError" in text for text in texts)
        assert any("boom" in text for text in texts)

    def test_result_without_error_is_not_shown(self) -> None:
        dialog, shown, _ = make_dialog()

        assert dialog.tick(SessionResult(SessionState.COMPLETED, None, None)) is False
        assert shown == []

    def test_same_result_is_presented_once(self) -> None:
        dialog, shown, _ = make_dialog()
        result = failure()

        assert dialog.tick(result) is True
        assert dialog.tick(result) is False

        assert len(shown) == 1

    def test_new_failure_is_presented_again(self) -> None:
        dialog, shown, _ = make_dialog()

        dialog.tick(failure("first"))
        dialog.tick(failure("second"))

        assert len(shown) == 2
        assert any("second" in text for text in collect_text(shown[1]))

    def test_close_only_hides_and_keeps_result(self) -> None:
        dialog, shown, hidden = make_dialog()
        result = failure()
        dialog.tick(result)

        click(find_button(shown[0], "Close"))

        assert hidden == [True]
        # Closing must not re-present or consume the terminal result.
        assert dialog.tick(result) is False
        assert len(shown) == 1
