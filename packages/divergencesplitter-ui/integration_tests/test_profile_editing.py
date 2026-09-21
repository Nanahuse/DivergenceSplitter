"""Profile editing through stable controls and public Flet events."""

from __future__ import annotations

import asyncio

from divergencesplitter_runtime.configuration.models import ResizeInterpolation
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp


async def _profile(start_test_app: StartApp, **kwargs):
    harness = await start_test_app(with_initial_profile=True, **kwargs)
    await harness.navigate("profile")
    await harness.wait_until(
        lambda: harness.value("profile-source-type") == "Video File"
    )
    return harness


async def test_profile_view_shows_empty_state_without_profile(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app()
    await harness.navigate("profile")

    empty = harness.find("profile-empty-state")
    assert empty.visible is True


async def test_profile_source_editing_updates_draft(start_test_app: StartApp) -> None:
    harness = await _profile(start_test_app, ndi_available=True, ndi_sources=("OBS",))

    await harness.select("profile-source-type", "Camera")
    camera = harness.find("profile-camera-device")
    await harness.select("profile-camera-device", camera.options[0].key or "")
    await harness.select("profile-source-type", "Video File")
    await harness.enter_text("profile-video-path", "edited.mp4")
    await harness.select("profile-source-type", "NDI")
    await harness.select("profile-ndi-source", "OBS")

    draft = harness.model.draft
    assert draft is not None
    assert draft.source.selected_type.value == "ndi"
    assert draft.source.video.path == "edited.mp4"
    assert draft.source.camera.device is not None
    assert draft.source.ndi.name == "OBS"


async def test_camera_device_mode_and_60fps_editing(start_test_app: StartApp) -> None:
    harness = await _profile(start_test_app)
    await harness.select("profile-source-type", "Camera")

    device = harness.find("profile-camera-device")
    await harness.select("profile-camera-device", device.options[0].key or "")
    mode = harness.find("profile-camera-mode")
    await harness.select("profile-camera-mode", mode.options[0].key or "")
    await harness.toggle("profile-request-60-fps", True)

    camera = harness.model.draft.source.camera  # type: ignore[union-attr]
    assert camera.device is not None
    assert camera.mode is not None
    assert camera.request_60_fps is True


async def test_frame_processing_editing_updates_draft(start_test_app: StartApp) -> None:
    harness = await _profile(start_test_app)
    await harness.toggle("profile-crop-enabled", True)
    for key, value in (
        ("profile-crop-left", "10"),
        ("profile-crop-right", "20"),
        ("profile-crop-top", "30"),
        ("profile-crop-bottom", "40"),
    ):
        await harness.enter_text(key, value)

    await harness.toggle("profile-resize-enabled", True)
    await harness.enter_text("profile-resize-width", "800")
    await harness.enter_text("profile-resize-height", "600")
    await harness.select("profile-resize-interpolation", "Cubic")
    await harness.toggle("profile-resize-references", True)

    draft = harness.model.draft
    assert draft is not None
    assert draft.source.transform.crop is not None
    assert (draft.source.transform.crop.left, draft.source.transform.crop.right) == (
        10,
        20,
    )
    resize = draft.source.transform.resize
    assert resize is not None
    assert (resize.width, resize.height) == (800, 600)
    assert resize.interpolation is ResizeInterpolation.CUBIC
    assert resize.resize_references is True


async def test_scenario_instance_editing_updates_draft(
    start_test_app: StartApp,
) -> None:
    harness = await _profile(start_test_app)
    await harness.select_tab(1)
    await harness.tap("profile-add-scenario")
    await harness.enter_text("profile-rpc-1", "tcp://127.0.0.1:54100")
    await harness.enter_text("profile-event-1", "tcp://127.0.0.1:54101")
    await harness.enter_text("profile-scenario-1", "next.py")
    await harness.tap("profile-remove-scenario-0")

    draft = harness.model.draft
    assert draft is not None
    assert len(draft.instances) == 1
    assert draft.instances[0].rpc_endpoint == "tcp://127.0.0.1:54100"
    assert draft.instances[0].event_endpoint == "tcp://127.0.0.1:54101"
    assert draft.instances[0].scenario == "next.py"


async def test_entering_input_refreshes_ndi_availability(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(
        with_initial_profile=True, ndi_available=True, ndi_sources=("OBS",)
    )
    await harness.navigate("profile")
    await harness.wait_until(lambda: harness.ndi_discovery.refresh_calls == 1)
    refreshes = harness.ndi_discovery.refresh_calls
    await asyncio.sleep(0.05)
    assert harness.ndi_discovery.refresh_calls == refreshes
    await harness.select("profile-source-type", "NDI")
    await harness.select("profile-ndi-source", "OBS")
    draft = harness.model.draft
    assert draft is not None
    assert draft.source.ndi.name == "OBS"


async def test_profile_edits_do_not_stop_active_runtime(
    start_test_app: StartApp,
) -> None:
    harness = await _profile(start_test_app)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.enter_text("profile-video-path", "edited.mp4")
    await harness.toggle("profile-crop-enabled", True)
    await harness.select_tab(1)
    await harness.enter_text("profile-scenario-0", "edited.py")

    assert harness.runtime.request_stop_calls == 0
    assert harness.controller.state.value == "RUNNING"
