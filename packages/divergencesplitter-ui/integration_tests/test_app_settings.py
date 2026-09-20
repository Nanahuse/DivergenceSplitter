"""Application Settings edits through the real Settings controls and lifecycle."""

from __future__ import annotations

from divergencesplitter_runtime.configuration.app_settings_json import load_app_settings
from divergencesplitter_runtime.configuration.models import Theme
from divergencesplitter_ui.navigation import AppView
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp


async def test_theme_change_is_persisted_and_applied_without_restart(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: bool(harness.runtime_factory.runtimes))
    await harness.navigate("settings")
    runtimes_before = len(harness.runtime_factory.runtimes)

    await harness.select("settings-theme", Theme.DARK.value)
    await harness.tap("settings-apply")

    assert harness.model.applied_app_settings.theme is Theme.DARK
    assert harness.page.dark_theme is not None
    assert load_app_settings(harness.settings_path).ui.theme is Theme.DARK
    assert len(harness.runtime_factory.runtimes) == runtimes_before


async def test_log_level_change_is_persisted_and_applied(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.navigate("settings")

    await harness.select("settings-log-level", "DEBUG")
    await harness.tap("settings-apply")

    assert harness.model.applied_app_settings.log_level == "DEBUG"
    assert load_app_settings(harness.settings_path).log_level == "DEBUG"


async def test_reaction_time_change_reloads_and_returns_to_running(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.navigate("settings")

    await harness.enter_text("settings-reaction-time", "30")
    await harness.tap("settings-apply")

    assert load_app_settings(harness.settings_path).reaction_time_ms == 30

    # The reload stops the running session and starts a new one with the new
    # reaction time; the shared UI must be intact afterwards.
    await harness.wait_until(lambda: len(harness.runtime_factory.runtimes) >= 2)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    assert harness.header.profile_path.value == str(harness.profile_a)
    assert harness.app is not None
    assert harness.app.active_view is AppView.SETTINGS
