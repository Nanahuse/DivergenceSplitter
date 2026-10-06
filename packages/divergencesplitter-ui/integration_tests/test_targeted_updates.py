"""Publicly observable page patching contracts."""

from __future__ import annotations

import asyncio

from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp


async def test_monitor_change_updates_only_changed_monitor_control(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    harness.page.update_calls.clear()
    harness.diagnostics.completed()

    await harness.wait_until(lambda: bool(harness.page.update_calls))
    targets = harness.page.update_calls[-1]
    assert harness.monitor.control not in targets
    assert targets


async def test_header_change_updates_only_header(start_test_app: StartApp) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    harness.page.update_calls.clear()
    await harness.navigate("profile")
    await harness.enter_text("profile-video-path", str(harness.video_b))
    await harness.navigate("monitor")

    await harness.wait_until(
        lambda: any(
            harness.header.control in update for update in harness.page.update_calls
        )
    )
    update = next(
        update
        for update in harness.page.update_calls
        if harness.header.control in update
    )
    assert harness.monitor.control not in update


async def test_preview_is_updated_only_while_profile_is_visible(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.navigate("profile")
    harness.page.update_calls.clear()
    await asyncio.sleep(0.1)
    visible_updates = list(harness.page.update_calls)

    await harness.navigate("settings")
    harness.page.update_calls.clear()
    await asyncio.sleep(0.1)

    assert visible_updates
    assert all(harness.monitor.control not in update for update in visible_updates)
    assert harness.app is not None and harness.app.profile_page is not None
    assert all(
        harness.app.profile_page.control not in update
        for update in harness.page.update_calls
    )


async def test_dialog_does_not_force_monitor_repaint(start_test_app: StartApp) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.navigate("settings")
    harness.page.update_calls.clear()
    await harness.enter_text("settings-reaction-time", "abc")
    await harness.tap("settings-apply")
    assert harness.monitor.control not in [
        target for update in harness.page.update_calls for target in update
    ]
