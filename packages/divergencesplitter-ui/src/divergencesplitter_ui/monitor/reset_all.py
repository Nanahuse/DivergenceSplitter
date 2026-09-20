"""Press-and-hold ``Reset All`` control for the Monitor Scenario Overview.

The three-second hold runs as a UI-only asyncio task, independent of the
Monitor snapshot cadence, so the animation is never driven by the Runtime
evaluation loop. A single task owns one press: it reports progress about
thirty times a second and fires the callback exactly once when the deadline is
reached. Release, pointer cancel, or any lost press cancels the task and
restores the button without firing.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import flet as ft

HOLD_TO_RESET_SECONDS = 3.0
HOLD_UPDATE_SECONDS = 1 / 30
RESET_LABEL = "Reset All"
HOLD_LABEL = "Hold to reset..."


class HoldToReset:
    """Measure one press-and-hold gesture with an injectable clock and sleep.

    The state machine is intentionally small: ``_pressed`` guards against a
    second task, ``_triggered`` guarantees at most one callback per press, and
    ``_task`` is the single hold task that must not outlive the control.
    """

    def __init__(
        self,
        on_reset: Callable[[], None],
        *,
        hold_seconds: float = HOLD_TO_RESET_SECONDS,
        update_seconds: float = HOLD_UPDATE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        self._on_reset = on_reset
        self._hold_seconds = hold_seconds
        self._update_seconds = update_seconds
        self._clock = clock
        self._sleep = sleep
        self._on_progress = on_progress
        self._pressed = False
        self._triggered = False
        self._progress = 0.0
        self._task: asyncio.Task[None] | None = None

    @property
    def progress(self) -> float:
        """The current hold progress in ``[0.0, 1.0]``."""

        return self._progress

    @property
    def pressed(self) -> bool:
        """Whether a press is currently being measured."""

        return self._pressed

    def press(self) -> None:
        """Start measuring; a second press while held is ignored."""

        if self._pressed:
            return
        self._pressed = True
        self._triggered = False
        self._set_progress(0.0)
        self._task = asyncio.ensure_future(self._hold())

    def release(self) -> None:
        """End the hold; fires nothing and restores the initial state."""

        self._cancel()

    def cancel(self) -> None:
        """Abandon the hold without firing, for a lost press."""

        self._cancel()

    def dispose(self) -> None:
        """Cancel any in-flight hold so no task outlives the control."""

        self._cancel()

    def _cancel(self) -> None:
        self._pressed = False
        self._triggered = False
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        self._set_progress(0.0)

    async def _hold(self) -> None:
        started = self._clock()
        try:
            while True:
                elapsed = self._clock() - started
                self._set_progress(min(elapsed / self._hold_seconds, 1.0))
                if elapsed >= self._hold_seconds:
                    break
                await self._sleep(self._update_seconds)
        except asyncio.CancelledError:
            return
        if self._triggered:
            return
        self._triggered = True
        self._set_progress(1.0)
        self._on_reset()

    def _set_progress(self, value: float) -> None:
        self._progress = value
        if self._on_progress is not None:
            self._on_progress(value)


class ResetAllButton:
    """An always-visible control that only fires after a completed hold."""

    def __init__(
        self,
        on_reset_all: Callable[[], None] | None = None,
        *,
        hold_seconds: float = HOLD_TO_RESET_SECONDS,
        update_seconds: float = HOLD_UPDATE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._label = ft.Text(RESET_LABEL)
        self._ring = ft.ProgressRing(
            value=0.0,
            width=16,
            height=16,
            stroke_width=2,
            visible=False,
        )
        self._icon = ft.Icon(ft.Icons.REFRESH, size=16)
        self._container = ft.Container(
            content=ft.Row(
                controls=[self._ring, self._icon, self._label],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            border_radius=6,
        )
        self._gesture = ft.GestureDetector(
            content=self._container,
            on_tap_down=self._handle_press,
            on_tap_up=self._handle_release,
            on_tap_cancel=self._handle_cancel,
        )
        self._hold = HoldToReset(
            on_reset_all or self._ignore,
            hold_seconds=hold_seconds,
            update_seconds=update_seconds,
            clock=clock,
            sleep=sleep,
            on_progress=self._apply_progress,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the Scenario Overview header."""

        return self._gesture

    @property
    def progress(self) -> float:
        return self._hold.progress

    def press(self) -> None:
        self._hold.press()
        self._refresh()

    def release(self) -> None:
        self._hold.release()
        self._refresh()

    def cancel(self) -> None:
        self._hold.cancel()
        self._refresh()

    def dispose(self) -> None:
        self._hold.dispose()

    @staticmethod
    def _ignore() -> None:
        pass

    def _handle_press(self, event: ft.TapEvent[ft.GestureDetector]) -> None:
        self.press()

    def _handle_release(self, event: ft.TapEvent[ft.GestureDetector]) -> None:
        self.release()

    def _handle_cancel(self, event: ft.Event[ft.GestureDetector]) -> None:
        self.cancel()

    def _apply_progress(self, value: float) -> None:
        self._ring.value = value
        holding = self._hold.pressed
        self._ring.visible = holding
        self._label.value = HOLD_LABEL if holding else RESET_LABEL
        self._refresh()

    def _refresh(self) -> None:
        page = _page_of(self._gesture)
        if page is not None:
            page.update(self._gesture)


def _page_of(control: ft.Control) -> ft.Page | None:
    """Return the owning page without raising before the control is mounted."""

    current: ft.Control | None = control
    while current is not None:
        if isinstance(current, ft.Page):
            return current
        current = getattr(current, "parent", None)
    return None
