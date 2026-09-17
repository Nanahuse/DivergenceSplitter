from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import flet as ft
from divergencesplitter import LiveSplitConnection
from divergencesplitter.frame.ndi import NdiSupport
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    ResizeInterpolation,
    RuntimeConfiguration,
)
from divergencesplitter_ui.configuration.page import ConfigurationPage
from divergencesplitter_ui.configuration.preview import PreviewController
from divergencesplitter_ui.monitor.input_preview import (
    PREVIEW_INTERVAL_SECONDS,  # noqa: F401
)
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionState,
)
from divergencesplitter_ui.settings import (
    CameraDevice,
    SettingsModel,
    SourceType,
)


class FakeCameraEnumerator:
    def list_devices(self) -> list[CameraDevice]:
        return cast(
            list[CameraDevice],
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=7,
                    modes=[
                        SimpleNamespace(
                            width=1280, height=720, fps=60.0, subtype_guid="MJPG"
                        ),
                        SimpleNamespace(
                            width=1920, height=1080, fps=30.0, subtype_guid="YUY2"
                        ),
                    ],
                )
            ],
        )


class FakeController:
    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
        self.started: list[Path] = []
        self.request_stop_calls = 0
        self.join_calls = 0
        self.log_levels: list[str] = []

    def start(self, path) -> None:
        if self.state in {
            SessionState.LOADING,
            SessionState.CONNECTING,
            SessionState.RUNNING,
            SessionState.STOPPING,
        }:
            raise SessionAlreadyActiveError(str(path))
        self.started.append(Path(path))
        self.state = SessionState.LOADING

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls += 1
        return True

    def set_log_level(self, level: str) -> None:
        self.log_levels.append(level)


class FakeDialogs:
    def __init__(self, *, open_result: Path | None = None) -> None:
        self.open_result = open_result

    async def open_file(self, **kwargs) -> Path | None:
        return self.open_result

    async def save_file(self, **kwargs) -> Path | None:
        return None

    async def confirm_discard(self) -> bool:
        return True


class FakeNdiDiscovery:
    def __init__(
        self, *, available: bool = True, sources: tuple[str, ...] = ()
    ) -> None:
        self._support = NdiSupport(available=available)
        self._sources = sources
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1

    def join(self, timeout: float | None = None) -> None:
        return None

    def support(self) -> NdiSupport:
        return self._support

    def sources(self) -> tuple[str, ...]:
        return self._sources


class FakePreviewController:
    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.stop_calls = 0
        self.transforms: list = []

    def update_transform(self, transform) -> None:
        self.transforms.append(transform)

    def start_draft(self, configuration, base_directory) -> None:
        self.started.append((configuration, base_directory))

    def stop(self) -> None:
        self.stop_calls += 1

    def take_frame(self):
        return None

    def normalize(self, frame):
        return frame

    @property
    def capture_settings(self):
        return None

    @property
    def error(self):
        return None


def camera_configuration() -> ApplicationConfiguration:
    return ApplicationConfiguration(
        version=1,
        source=CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
            CameraModeConfiguration(1280, 720, 60.0, "MJPG"),
            False,
        ),
        instances=(
            InstanceConfiguration(LiveSplitConnection("rpc", "event"), "scenario.py"),
        ),
        runtime=RuntimeConfiguration("INFO"),
    )


def make_page(
    *,
    configuration: ApplicationConfiguration | None = None,
    ndi: FakeNdiDiscovery | None = None,
    controller: FakeController | None = None,
    preview: FakePreviewController | None = None,
) -> ConfigurationPage:
    model = SettingsModel(FakeCameraEnumerator())
    model.open_configuration(
        configuration or camera_configuration(), Path("config.json")
    )
    return ConfigurationPage(
        cast(SessionController, controller or FakeController()),
        model,
        FakeDialogs(),
        ndi_discovery=cast(NdiDiscovery, ndi or FakeNdiDiscovery()),
        preview_controller=cast(PreviewController, preview or FakePreviewController()),
    )


def fire(handler, control, data=None) -> None:
    handler(ft.Event("change", control, data=data))


def collect_text(control: ft.Control) -> list[str]:
    found: list[str] = []
    stack = [control]
    while stack:
        item = stack.pop()
        value = getattr(item, "value", None)
        if isinstance(value, str):
            found.append(value)
        stack.extend(getattr(item, "controls", None) or ())
        content = getattr(item, "content", None)
        if content is not None:
            stack.append(content)
        title = getattr(item, "title", None)
        if isinstance(title, ft.Control):
            stack.append(title)
    return found


class TestPageBuild:
    def test_page_renders_title(self) -> None:
        page = make_page()

        assert "Configuration" in collect_text(page.control)


class TestSourceType:
    def test_switch_to_video_updates_model_and_visibility(self) -> None:
        page = make_page()
        source = page._source
        page.tick(SessionState.IDLE, visible=True)

        source._source_type.value = "Video File"
        fire(source._on_source_type_selected, source._source_type)

        assert page._model.draft is not None
        assert page._model.draft.source.selected_type is SourceType.VIDEO
        assert source._camera_group.visible is False
        assert source._video_group.visible is True

    def test_switch_to_ndi_updates_model(self) -> None:
        page = make_page(ndi=FakeNdiDiscovery(available=True, sources=("OBS",)))
        source = page._source
        page.tick(SessionState.IDLE, visible=True)

        source._source_type.value = "NDI"
        fire(source._on_source_type_selected, source._source_type)

        assert page._model.draft is not None
        assert page._model.draft.source.selected_type is SourceType.NDI
        assert source._ndi_group.visible is True


class TestCamera:
    def test_device_and_mode_selection(self) -> None:
        page = make_page()
        source = page._source
        page.populate()
        page.tick(SessionState.IDLE, visible=True)

        device_label = source._device.options[0].key
        source._device.value = device_label
        fire(source._on_device_selected, source._device)

        assert page._model.draft is not None
        assert page._model.draft.source.camera.device == CameraDeviceConfiguration(
            CameraBackend.DIRECT_SHOW, "USB Camera", 7
        )
        assert source._mode.options

        mode_label = source._mode.options[0].key
        source._mode.value = mode_label
        fire(source._on_mode_selected, source._mode)

        assert page._model.draft.source.camera.mode == CameraModeConfiguration(
            1280, 720, 60.0, "MJPG"
        )

    def test_request_60_fps(self) -> None:
        page = make_page()
        source = page._source
        page.tick(SessionState.IDLE, visible=True)

        source._request_60_fps.value = True
        fire(source._on_request_60_fps_changed, source._request_60_fps)

        assert page._model.draft is not None
        assert page._model.draft.source.camera.request_60_fps is True


class TestVideo:
    def test_path_edit_updates_model(self) -> None:
        page = make_page()
        source = page._source
        page.tick(SessionState.IDLE, visible=True)

        source._video_path.value = "clip.mp4"
        fire(source._on_video_path_changed, source._video_path)

        assert page._model.draft is not None
        assert page._model.draft.source.video.path == "clip.mp4"


class TestNdiAvailability:
    def test_unavailable_shows_disabled_option_and_status(self) -> None:
        page = make_page(ndi=FakeNdiDiscovery(available=False))
        source = page._source

        page.tick(SessionState.IDLE, visible=True)

        labels = [option.key or "" for option in source._source_type.options]
        assert labels[-1].endswith("(Unavailable)")
        assert source._source_type.options[-1].disabled is True
        assert "not available" in source._ndi_status.value


class TestFrameProcessing:
    def test_crop_toggle_and_values(self) -> None:
        page = make_page()
        section = page._frame_processing
        page.tick(SessionState.IDLE, visible=True)

        section._crop_enabled.value = True
        fire(section._on_crop_enabled_changed, section._crop_enabled, data=True)
        section._crop_left.value = "10"
        section._crop_right.value = "20"
        section._crop_top.value = "30"
        section._crop_bottom.value = "40"
        fire(section._on_crop_changed, section._crop_left)

        assert page._model.draft is not None
        crop = page._model.draft.source.transform.crop
        assert crop is not None
        assert (crop.left, crop.right, crop.top, crop.bottom) == (10, 20, 30, 40)

        section._crop_enabled.value = False
        fire(section._on_crop_enabled_changed, section._crop_enabled, data=False)

        assert page._model.draft.source.transform.crop is None

    def test_resize_toggle_and_interpolation(self) -> None:
        page = make_page()
        section = page._frame_processing
        page.tick(SessionState.IDLE, visible=True)

        section._resize_enabled.value = True
        fire(section._on_resize_enabled_changed, section._resize_enabled, data=True)
        section._resize_width.value = "800"
        section._resize_height.value = "600"
        fire(section._on_resize_changed, section._resize_width)
        section._resize_interpolation.value = "Cubic"
        fire(
            section._on_resize_interpolation_changed,
            section._resize_interpolation,
        )

        draft = page._model.draft
        assert draft is not None
        resize = draft.source.transform.resize
        assert resize is not None
        assert (resize.width, resize.height) == (800, 600)
        assert resize.interpolation is ResizeInterpolation.CUBIC

        section._resize_references.value = True
        fire(section._on_resize_references_changed, section._resize_references)
        assert draft.source.transform.resize is not None
        assert draft.source.transform.resize.resize_references is True


class TestInstances:
    def test_add_remove_and_edit(self) -> None:
        page = make_page()
        section = page._instances
        page.tick(SessionState.IDLE, visible=True)

        fire(section._on_add, section._control)
        assert page._model.draft is not None
        assert len(page._model.draft.instances) == 2

        section._rows[1].rpc.value = "tcp://127.0.0.1:54000"
        fire(section._rows[1].rpc.on_change, section._rows[1].rpc)
        section._rows[1].event.value = "tcp://127.0.0.1:54001"
        fire(section._rows[1].event.on_change, section._rows[1].event)
        section._rows[1].scenario.value = "next.py"
        fire(section._rows[1].scenario.on_change, section._rows[1].scenario)

        assert page._model.draft.instances[1].rpc_endpoint == "tcp://127.0.0.1:54000"
        assert page._model.draft.instances[1].event_endpoint == "tcp://127.0.0.1:54001"
        assert page._model.draft.instances[1].scenario == "next.py"

        section._on_remove(0)
        assert len(page._model.draft.instances) == 1


class TestTick:
    def test_dirty_indicator_and_permissions(self) -> None:
        page = make_page()
        assert page.tick(SessionState.IDLE, visible=True) is True
        assert page._config_path.value == "config.json"

        page._model.set_log_level("OFF")
        page.tick(SessionState.IDLE, visible=True)
        assert page._config_path.value.endswith(" *")
        assert page._log_level.value == "OFF"

    def test_transition_state_disables_source_editing(self) -> None:
        page = make_page()
        page.tick(SessionState.IDLE, visible=True)

        page.tick(SessionState.CONNECTING, visible=True)

        assert page._source._source_type.disabled is True
        assert page._new_button.disabled is True

    def test_hidden_tick_is_cheap_and_stops_preview(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        page.tick(SessionState.IDLE, visible=False)

        assert page._pending_preview_command is not None


class TestPreviewSync:
    def test_camera_draft_schedules_start(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())

        assert preview.started

    def test_switching_to_video_stops_draft_preview(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())

        page._model.set_source_type(SourceType.VIDEO)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())

        assert preview.stop_calls >= 1

    def test_active_runtime_does_not_start_draft_preview(self) -> None:
        preview = FakePreviewController()
        controller = FakeController()
        controller.state = SessionState.RUNNING
        page = make_page(preview=preview, controller=controller)

        page.tick(SessionState.RUNNING, visible=True)
        asyncio.run(page.pump_preview())

        assert preview.started == []


class TestPreviewUpdateTargets:
    def test_targets_include_the_preview_control(self) -> None:
        page = make_page()

        targets = page.preview_update_targets()

        assert page.preview.control in targets
        assert all(isinstance(target, ft.Control) for target in targets)


class TestUnsavedEditsDoNotStopRuntime:
    def _running_page(self, **kwargs):
        controller = kwargs.pop("controller", None) or FakeController()
        controller.state = SessionState.RUNNING
        page = make_page(controller=controller, **kwargs)
        page.populate()
        page.tick(SessionState.RUNNING, visible=True)
        return page, controller

    def _assert_runtime_untouched(self, controller) -> None:
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert controller.state is SessionState.RUNNING

    def test_camera_edits_do_not_stop_runtime(self) -> None:
        page, controller = self._running_page()
        source = page._source

        device_label = source._device.options[0].key
        source._device.value = device_label
        fire(source._on_device_selected, source._device)
        mode_label = source._mode.options[0].key
        source._mode.value = mode_label
        fire(source._on_mode_selected, source._mode)
        source._request_60_fps.value = True
        fire(source._on_request_60_fps_changed, source._request_60_fps)

        self._assert_runtime_untouched(controller)
        assert page._model.is_dirty

    def test_source_type_change_does_not_stop_runtime(self) -> None:
        page, controller = self._running_page()
        source = page._source

        source._source_type.value = "Video File"
        fire(source._on_source_type_selected, source._source_type)

        self._assert_runtime_untouched(controller)
        assert page._model.draft is not None
        assert page._model.draft.source.selected_type is SourceType.VIDEO

    def test_ndi_change_does_not_stop_runtime(self) -> None:
        page, controller = self._running_page(
            ndi=FakeNdiDiscovery(available=True, sources=("OBS",))
        )
        source = page._source

        source._source_type.value = "NDI"
        fire(source._on_source_type_selected, source._source_type)
        source._ndi_source.value = "OBS"
        fire(source._on_ndi_source_selected, source._ndi_source)

        self._assert_runtime_untouched(controller)
        assert page._model.draft is not None
        assert page._model.draft.source.ndi.name == "OBS"

    def test_crop_and_resize_do_not_stop_runtime(self) -> None:
        page, controller = self._running_page()
        section = page._frame_processing

        section._crop_enabled.value = True
        fire(section._on_crop_enabled_changed, section._crop_enabled, data=True)
        section._resize_enabled.value = True
        fire(section._on_resize_enabled_changed, section._resize_enabled, data=True)
        section._resize_interpolation.value = "Cubic"
        fire(
            section._on_resize_interpolation_changed,
            section._resize_interpolation,
        )

        self._assert_runtime_untouched(controller)

    def test_instance_edits_do_not_stop_runtime(self) -> None:
        page, controller = self._running_page()
        section = page._instances

        section._rows[0].scenario.value = "next.py"
        fire(section._rows[0].scenario.on_change, section._rows[0].scenario)
        section._rows[0].rpc.value = "tcp://127.0.0.1:54000"
        fire(section._rows[0].rpc.on_change, section._rows[0].rpc)
        fire(section._on_add, section._control)
        section._on_remove(0)

        self._assert_runtime_untouched(controller)
        assert page._model.is_dirty

    def test_status_reports_unsaved_input_change(self) -> None:
        page, _ = self._running_page()

        page._on_input_changed()

        assert page._actions.status == "Input changed; save to apply."

    def test_log_level_applies_live_without_restart(self) -> None:
        page, controller = self._running_page()

        page._log_level.value = "OFF"
        fire(page._on_log_level, page._log_level)

        assert page._model.draft is not None
        assert page._model.draft.log_level == "OFF"
        assert controller.log_levels == ["OFF"]
        self._assert_runtime_untouched(controller)

    def test_reaction_time_edits_draft_only(self) -> None:
        page, controller = self._running_page()

        page._reaction_time.value = "30"
        fire(page._on_reaction_time, page._reaction_time)

        assert page._model.draft is not None
        assert page._model.draft.reaction_time_ms == 30
        self._assert_runtime_untouched(controller)
        assert page._model.is_dirty

    def test_draft_change_does_not_transition_session_state(self) -> None:
        page, controller = self._running_page()

        page._on_input_changed()

        assert controller.state is not SessionState.STOPPING
        assert controller.state is SessionState.RUNNING


class TestTeardown:
    def test_teardown_stops_preview_and_ndi(self) -> None:
        preview = FakePreviewController()
        ndi = FakeNdiDiscovery()
        page = make_page(preview=preview, ndi=ndi)

        page.teardown()

        assert preview.stop_calls == 1
