"""Publicly observable page patching contracts."""

from __future__ import annotations

import pytest
from divergencesplitter.frame.camera import CameraCaptureSettings
from divergencesplitter_runtime.configuration.models import (
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
)
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp
from integration_tests.harness import Harness


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
    assert harness.app is not None and harness.app.profile_page is not None
    await harness.navigate("profile")
    profile_page = harness.app.profile_page
    preview_controls = (
        profile_page.preview.control,
        profile_page.input.opened_camera_label,
    )
    harness.preview_controller.capture_settings = CameraCaptureSettings(
        width=1280, height=720, fps=30.0
    )
    harness.page.update_calls.clear()
    await harness.apply_profile_preview_cycle()
    assert (
        profile_page.input.opened_camera_label.value
        == "Opened camera: 1280×720 @ 30.00 FPS"
    )
    assert harness.page.update_calls == [preview_controls]

    await harness.navigate("settings")
    harness.preview_controller.capture_settings = CameraCaptureSettings(
        width=1920, height=1080, fps=60.0
    )
    harness.page.update_calls.clear()
    await harness.apply_profile_preview_cycle()

    assert harness.page.update_calls == []
    assert (
        profile_page.input.opened_camera_label.value
        == "Opened camera: 1280×720 @ 30.00 FPS"
    )

    await harness.navigate("profile")
    harness.page.update_calls.clear()
    await harness.apply_profile_preview_cycle()
    assert (
        profile_page.input.opened_camera_label.value
        == "Opened camera: 1920×1080 @ 60.00 FPS"
    )
    assert harness.page.update_calls == [preview_controls]


def _camera_profile(harness: Harness) -> None:
    harness.model.create_default_camera_profile(
        harness.profile_a,
        CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
        CameraModeConfiguration(1280, 720, 60.0, "MJPG"),
    )


@pytest.mark.parametrize("destination", ["settings", "monitor"])
async def test_navigation_stops_camera_preview_without_hidden_ui_updates(
    start_test_app: StartApp, destination: str
) -> None:
    harness = await start_test_app()
    _camera_profile(harness)
    await harness.navigate("profile")
    await harness.wait_until(lambda: len(harness.preview_controller.started) == 1)

    assert harness.app is not None and harness.app.profile_page is not None
    profile_page = harness.app.profile_page
    previous_label = profile_page.input.opened_camera_label.value
    await harness.navigate(destination)
    await harness.wait_until(lambda: harness.preview_controller.stop_calls == 1)

    harness.preview_controller.capture_settings = CameraCaptureSettings(
        width=1920, height=1080, fps=60.0
    )
    harness.page.update_calls.clear()
    await harness.apply_profile_preview_cycle()

    assert harness.preview_controller.stop_calls == 1
    assert len(harness.preview_controller.started) == 1
    assert profile_page.input.opened_camera_label.value == previous_label
    assert harness.page.update_calls == []


async def test_navigation_cancels_camera_preview_start_before_capture_begins(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app()
    _camera_profile(harness)

    await harness.navigate("profile")
    await harness.navigate("settings")
    await harness.apply_profile_preview_cycle()

    assert harness.preview_controller.started == []
    assert harness.preview_controller.stop_calls == 0


async def test_camera_preview_restarts_after_returning_to_profile(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app()
    _camera_profile(harness)
    await harness.navigate("profile")
    await harness.wait_until(lambda: len(harness.preview_controller.started) == 1)

    await harness.navigate("settings")
    await harness.wait_until(lambda: harness.preview_controller.stop_calls == 1)
    await harness.navigate("profile")
    await harness.wait_until(lambda: len(harness.preview_controller.started) == 2)

    await harness.navigate("monitor")
    await harness.wait_until(lambda: harness.preview_controller.stop_calls == 2)
    await harness.navigate("profile")
    await harness.wait_until(lambda: len(harness.preview_controller.started) == 3)

    assert harness.preview_controller.stop_calls == 2


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
