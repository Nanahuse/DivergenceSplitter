"""Switching Profiles updates the shared header and the Profile page."""

from __future__ import annotations

from divergencesplitter_ui.navigation import AppView
from divergencesplitter_ui.session import is_active

from integration_tests.conftest import StartApp


async def test_opening_another_profile_refreshes_header_and_input(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=True)
    await harness.wait_until(lambda: not is_active(harness.controller.state))
    await harness.navigate("profile")
    harness.dialogs.queue_open(harness.profile_b)

    await harness.tap("profile-open")

    await harness.wait_until(
        lambda: harness.header.profile_path.value == str(harness.profile_b)
    )
    assert harness.value("profile-video-path") == str(harness.video_b)
    assert harness.value("profile-scenario-0") == str(harness.scenario_b)
    assert harness.value("profile-video-path") != str(harness.video_a)


async def test_profile_changed_while_monitor_shows_is_reflected_on_return(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=True)
    assert harness.app is not None
    await harness.wait_until(lambda: not is_active(harness.controller.state))
    assert harness.app.active_view is AppView.MONITOR

    # Open the second Profile from the always-visible header while the Profile
    # page itself is hidden.
    harness.dialogs.queue_open(harness.profile_b)
    await harness.tap("profile-open")
    await harness.wait_until(
        lambda: harness.header.profile_path.value == str(harness.profile_b)
    )
    assert harness.app.active_view is AppView.MONITOR

    await harness.navigate("profile")

    await harness.wait_until(
        lambda: harness.value("profile-video-path") == str(harness.video_b)
    )
    assert harness.value("profile-scenario-0") == str(harness.scenario_b)
    assert harness.value("profile-video-path") != str(harness.video_a)
