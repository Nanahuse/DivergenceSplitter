"""Official Flet smoke test: the packaged app runs and renders in real Flutter.

Run with ``uv run flet test --tests-dir integration_smoke``. The app under test
is the shipped ``src/main.py`` running on-device with embedded Python, and the
test drives the real Flutter client through the official ``flet_app`` fixture.
"""

from __future__ import annotations

import flet.testing as ftt

VIEWS = ("monitor", "diagnostics", "profile", "settings", "about")


async def test_navigation_and_shared_header_render(flet_app: ftt.FletTestApp) -> None:
    tester = flet_app.tester
    await tester.pump_and_settle()

    assert (await tester.find_by_key("nav-monitor")).count == 1
    assert (await tester.find_by_key("profile-path")).count == 1

    for view in VIEWS:
        await tester.tap(await tester.find_by_key(f"nav-{view}"))
        await tester.pump_and_settle()
        assert (await tester.find_by_key("profile-path")).count == 1


async def test_settings_controls_render(flet_app: ftt.FletTestApp) -> None:
    tester = flet_app.tester
    await tester.pump_and_settle()

    await tester.tap(await tester.find_by_key("nav-settings"))
    await tester.pump_and_settle()

    assert (await tester.find_by_key("settings-theme")).count == 1
    assert (await tester.find_by_key("settings-log-level")).count == 1
    assert (await tester.find_by_key("settings-reaction-time")).count == 1
