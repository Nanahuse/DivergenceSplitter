"""Reset All press-and-hold behavior, driven without real-time waits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator

import flet as ft
import pytest
from divergencesplitter_runtime.configuration.models import Theme
from divergencesplitter_ui.monitor.page import Monitor
from divergencesplitter_ui.monitor.reset_all import (
    HOLD_LABEL,
    RESET_LABEL,
    HoldToReset,
    ResetAllButton,
)
from divergencesplitter_ui.monitor.scenario_overview import ScenarioOverviewPanel

pytestmark = pytest.mark.asyncio


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


def instant_sleep(
    clock: FakeClock,
) -> Callable[[float], Awaitable[None]]:
    """Advance the clock without yielding, so a hold completes in one step."""

    async def sleep(seconds: float) -> None:
        clock.seconds += seconds

    return sleep


def yielding_sleep(
    clock: FakeClock,
) -> Callable[[float], Awaitable[None]]:
    """Advance the clock and yield, so a test can interrupt mid-hold."""

    async def sleep(seconds: float) -> None:
        clock.seconds += seconds
        await asyncio.sleep(0)

    return sleep


def collect_text(control: ft.Control) -> list[str]:
    found: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        found.append(value)
    for child in getattr(control, "controls", None) or ():
        found.extend(collect_text(child))
    content = getattr(control, "content", None)
    if content is not None:
        found.extend(collect_text(content))
    return found


def iter_controls(control: ft.Control) -> Iterator[ft.Control]:
    yield control
    for child in getattr(control, "controls", None) or ():
        yield from iter_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from iter_controls(content)


async def drain(steps: int = 1) -> None:
    for _ in range(steps):
        await asyncio.sleep(0)


class TestHoldToReset:
    async def test_full_hold_fires_exactly_once(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        hold = HoldToReset(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )

        hold.press()
        await drain()

        assert calls == [1]
        assert hold.progress == 1.0
        assert hold.pressed is True

    async def test_holding_past_the_deadline_does_not_refire(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        hold = HoldToReset(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )

        hold.press()
        await drain()
        await drain(5)
        assert calls == [1]

        hold.release()
        await drain()
        assert calls == [1]

    async def test_short_press_does_not_fire(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        hold = HoldToReset(
            lambda: calls.append(1), clock=clock, sleep=yielding_sleep(clock)
        )

        hold.press()
        await drain(10)
        assert 0.0 < hold.progress < 1.0

        hold.release()
        await drain(2)

        assert calls == []
        assert hold.progress == 0.0

    async def test_cancel_does_not_fire_and_clears_progress(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        hold = HoldToReset(
            lambda: calls.append(1), clock=clock, sleep=yielding_sleep(clock)
        )

        hold.press()
        await drain()
        hold.cancel()
        await drain(2)

        assert calls == []
        assert hold.progress == 0.0
        assert hold.pressed is False

    async def test_release_allows_another_hold(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        hold = HoldToReset(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )

        hold.press()
        await drain()
        hold.release()
        hold.press()
        await drain()

        assert calls == [1, 1]

    async def test_second_press_while_held_is_ignored(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        hold = HoldToReset(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )

        hold.press()
        hold.press()
        await drain()

        assert calls == [1]


class TestResetAllButton:
    async def test_button_fires_callback_after_a_full_hold(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        button = ResetAllButton(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )

        button.press()
        await drain()

        assert calls == [1]
        assert button.progress == 1.0
        button.release()
        assert button.progress == 0.0

    async def test_pointer_cancel_does_not_fire(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        button = ResetAllButton(
            lambda: calls.append(1), clock=clock, sleep=yielding_sleep(clock)
        )

        button.press()
        await drain()
        button.cancel()
        await drain(2)

        assert calls == []
        assert button.progress == 0.0

    async def test_label_starts_normal(self) -> None:
        clock = FakeClock()
        button = ResetAllButton(lambda: None, clock=clock, sleep=instant_sleep(clock))

        assert RESET_LABEL in collect_text(button.control)

    async def test_label_shows_hold_while_pressed(self) -> None:
        clock = FakeClock()
        button = ResetAllButton(lambda: None, clock=clock, sleep=instant_sleep(clock))

        button.press()
        assert HOLD_LABEL in collect_text(button.control)
        await drain()
        button.release()
        texts = collect_text(button.control)
        assert RESET_LABEL in texts
        assert HOLD_LABEL not in texts


class TestScenarioOverviewHeader:
    async def test_header_shows_reset_all(self) -> None:
        panel = ScenarioOverviewPanel()

        texts = collect_text(panel.control)

        assert "Scenario Overview" in texts
        assert RESET_LABEL in texts

    async def test_injected_button_reaches_the_callback(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        button = ResetAllButton(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )
        panel = ScenarioOverviewPanel(reset_all=button)

        panel.reset_all.press()
        await drain()

        assert calls == [1]
        assert any(
            control is button.control for control in iter_controls(panel.control)
        )


class TestMonitorWiring:
    async def test_monitor_passes_an_injected_reset_button_to_the_panel(self) -> None:
        calls: list[int] = []
        clock = FakeClock()
        button = ResetAllButton(
            lambda: calls.append(1), clock=clock, sleep=instant_sleep(clock)
        )
        monitor = Monitor(Theme.LIGHT, reset_all=button)

        monitor.scenario_overview.reset_all.press()
        await drain()

        assert calls == [1]
        assert monitor.scenario_overview.reset_all is button
