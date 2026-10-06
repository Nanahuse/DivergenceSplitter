"""The mounted application shell: navigation, shared header, Profile controls."""

from __future__ import annotations

from divergencesplitter_ui.navigation import AppView
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp


async def test_mounts_on_monitor_with_the_shared_header(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)

    assert harness.app is not None
    assert harness.app.active_view is AppView.MONITOR
    await harness.wait_until(
        lambda: harness.header.profile_path.value == str(harness.profile_a)
    )
    for view in ("monitor", "diagnostics", "profile", "settings", "about"):
        assert harness.find(f"nav-{view}") is not None


async def test_navigation_reveals_the_profile_controls(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)

    await harness.navigate("profile")

    await harness.wait_until(
        lambda: harness.value("profile-source-type") == "Video File"
    )
    assert harness.value("profile-video-path") == str(harness.video_a)
    assert harness.value("profile-scenario-0") == str(harness.scenario_a)


async def test_navigation_reveals_the_settings_controls(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(release_on_run=False)

    await harness.navigate("settings")

    assert harness.find("settings-theme") is not None
    assert harness.find("settings-log-level") is not None
    assert harness.find("settings-reaction-time") is not None
    assert harness.find("settings-apply") is not None


async def test_navigation_is_collapsed_by_default_and_can_expand(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)

    assert harness.navigation.expanded is False
    await harness.tap("nav-toggle")
    assert harness.navigation.expanded is True
    for view in ("monitor", "diagnostics", "profile", "settings", "about"):
        assert harness.find(f"nav-{view}").content.controls[1].visible is True
    await harness.tap("nav-toggle")
    assert harness.navigation.expanded is False


async def test_navigation_toggle_preserves_active_view(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.navigate("settings")

    await harness.tap("nav-toggle")
    await harness.tap("nav-toggle")

    assert harness.app is not None
    assert harness.app.active_view is AppView.SETTINGS
    assert harness.navigation.selected is AppView.SETTINGS


async def test_navigation_does_not_stop_active_runtime(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    for view in ("profile", "settings", "about", "monitor"):
        await harness.navigate(view)

    assert harness.runtime_factory.runtimes[-1].request_stop_calls == 0
    assert harness.controller.state is SessionState.RUNNING
