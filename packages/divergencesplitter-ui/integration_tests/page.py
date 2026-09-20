"""In-process Flet page host and control-driving helpers.

These integration tests mount the real ``FletApplication`` on a recording page:
every control is a genuine Flet control and every interaction is dispatched
through the control's own public event handler (``on_click`` / ``on_select`` /
``on_change``), so the real event and synchronization path runs. The page object
only records ``update`` calls instead of sending patches to a Flutter client.
"""

from __future__ import annotations

import inspect
from typing import Any

import flet as ft


class FakeWindow:
    """The subset of ``page.window`` the application touches."""

    def __init__(self) -> None:
        self.width: int | None = None
        self.height: int | None = None
        self.prevent_close = False
        self.on_event: Any = None
        self.destroyed = False

    async def destroy(self) -> None:
        self.destroyed = True


class RecordingPage:
    """A minimal ``ft.Page`` stand-in that records updates and dialogs."""

    def __init__(self) -> None:
        self.title = ""
        self.window = FakeWindow()
        self.controls: list[Any] = []
        self.theme_mode: Any = None
        self.theme: Any = None
        self.dark_theme: Any = None
        self.update_calls: list[tuple[Any, ...]] = []
        self.dialogs: list[Any] = []

    def add(self, *controls: Any) -> None:
        self.controls.extend(controls)

    def update(self, *controls: Any) -> None:
        self.update_calls.append(controls)

    def show_dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        if self.dialogs:
            self.dialogs.pop()


def iter_controls(root: Any):
    """Yield ``root`` and every nested Flet control reachable from it."""

    stack = list(root) if isinstance(root, list) else [root]
    seen: set[int] = set()
    while stack:
        control = stack.pop()
        if control is None or id(control) in seen:
            continue
        seen.add(id(control))
        if isinstance(control, ft.Control):
            yield control
        for attribute in ("controls", "content"):
            value = getattr(control, attribute, None)
            if isinstance(value, list):
                stack.extend(value)
            elif value is not None:
                stack.append(value)


def find_by_key(page: RecordingPage, key: str) -> ft.Control:
    """Find one control by its stable Flet key, failing loudly when absent."""

    for control in iter_controls(page.controls):
        if getattr(control, "key", None) == key:
            return control
    raise KeyError(f"no control with key {key!r}")


def collect_text(root: Any) -> str:
    """Join the visible string values of a control tree for text assertions."""

    values: list[str] = []
    for control in iter_controls(root):
        for attribute in ("value", "label", "text"):
            value = getattr(control, attribute, None)
            if isinstance(value, str) and value:
                values.append(value)
    return "\n".join(values)


async def dispatch_event(handler: Any, control: ft.Control, name: str) -> None:
    """Invoke one public control event handler, awaiting async handlers."""

    if handler is None:
        raise AssertionError(f"{control!r} has no {name} handler")
    result = handler(ft.Event(name, control))
    if inspect.isawaitable(result):
        await result


async def tap(control: ft.Control) -> None:
    """Dispatch the control's public click handler, awaiting async handlers."""

    await dispatch_event(getattr(control, "on_click", None), control, "click")


async def select(control: ft.Dropdown, value: str) -> None:
    """Choose a dropdown option and dispatch its public select handler."""

    control.value = value
    await dispatch_event(getattr(control, "on_select", None), control, "select")


async def enter_text(control: ft.TextField, value: str) -> None:
    """Replace a text field's value and dispatch its public change handler."""

    control.value = value
    await dispatch_event(getattr(control, "on_change", None), control, "change")
