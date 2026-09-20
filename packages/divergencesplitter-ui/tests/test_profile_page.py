from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import flet as ft
from divergencesplitter import LiveSplitConnection
from divergencesplitter.frame.ndi import NdiSupport
from divergencesplitter_runtime.configuration.models import (
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    Profile,
    ResizeInterpolation,
    VideoSourceConfiguration,
)
from divergencesplitter_ui.configuration.preview import PreviewController
from divergencesplitter_ui.monitor.input_preview import (
    PREVIEW_INTERVAL_SECONDS,  # noqa: F401
)
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.profile.page import ProfilePage, ProfileTab
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

BASE = Path.cwd()


def p(name: str) -> str:
    return str(BASE / name)


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

    def start(self, path, *, app_settings) -> None:
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

    def start_draft(self, configuration) -> None:
        self.started.append(configuration)

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


def camera_profile() -> Profile:
    return Profile(
        version=1,
        source=CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
            CameraModeConfiguration(1280, 720, 60.0, "MJPG"),
            False,
        ),
        instances=(
            InstanceConfiguration(
                LiveSplitConnection("rpc", "event"), p("scenario.py")
            ),
        ),
    )


def make_page(
    *,
    profile: Profile | None = None,
    empty: bool = False,
    profile_path: Path | None = None,
    ndi: FakeNdiDiscovery | None = None,
    controller: FakeController | None = None,
    preview: FakePreviewController | None = None,
    statuses: list[str] | None = None,
) -> ProfilePage:
    model = SettingsModel(FakeCameraEnumerator())
    if not empty:
        model.open_profile(
            profile or camera_profile(), profile_path or Path("config.json")
        )
    recorded = statuses if statuses is not None else []
    return ProfilePage(
        cast(SessionController, controller or FakeController()),
        model,
        FakeDialogs(),
        on_status=recorded.append,
        ndi_discovery=cast(NdiDiscovery, ndi or FakeNdiDiscovery()),
        preview_controller=cast(PreviewController, preview or FakePreviewController()),
    )


def fire(handler, control, data=None) -> None:
    handler(ft.Event("change", control, data=data))


def collect_controls(root: ft.Control) -> list[ft.Control]:
    found: list[ft.Control] = []
    stack: list[object] = [root]
    while stack:
        item = stack.pop()
        if not isinstance(item, ft.Control):
            continue
        found.append(item)
        controls = getattr(item, "controls", None)
        if isinstance(controls, (list, tuple)):
            stack.extend(controls)
        elif isinstance(controls, ft.Control):
            stack.append(controls)
        for attribute in ("content", "title"):
            child = getattr(item, attribute, None)
            if isinstance(child, ft.Control):
                stack.append(child)
    return found


def collect_text(control: ft.Control) -> list[str]:
    found: list[str] = []
    stack = [control]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.append(item)
            continue
        for attribute in ("value", "label", "content"):
            candidate = getattr(item, attribute, None)
            if isinstance(candidate, str):
                found.append(candidate)
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

        assert "Profile" in collect_text(page.control)

    def test_page_has_no_system_settings(self) -> None:
        page = make_page()

        labels = collect_text(page.control)
        assert "System" not in labels
        assert "Theme" not in labels
        assert "Reaction time (ms)" not in labels
        assert "Log level (OFF / DEBUG: all details)" not in labels


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
    def test_input_starts_ndi_detection_and_enables_available_source(self) -> None:
        discovery = NdiDiscovery(
            support_probe=lambda: NdiSupport(True),
            source_lister=lambda timeout: ("Gaming PC (OBS)",),
        )
        page = make_page(ndi=cast(FakeNdiDiscovery, discovery))
        assert discovery.support() is None

        page.tick(SessionState.IDLE, visible=True)
        discovery.join(2)
        page.tick(SessionState.IDLE, visible=True)

        assert discovery.support() == NdiSupport(True)
        assert page._model.ndi_available is True
        option = next(
            item for item in page._source._source_type.options if item.key == "NDI"
        )
        assert option.disabled is False

    def test_ndi_refresh_runs_on_input_entry_not_every_tick(self) -> None:
        discovery = FakeNdiDiscovery()
        page = make_page(ndi=discovery)
        page.tick(SessionState.IDLE, visible=False)
        assert discovery.refresh_calls == 0
        page.tick(SessionState.IDLE, visible=True)
        page.tick(SessionState.IDLE, visible=True)
        assert discovery.refresh_calls == 1
        page.select_tab(ProfileTab.SCENARIOS)
        page.select_tab(ProfileTab.INPUT)
        assert discovery.refresh_calls == 2
        page.tick(SessionState.IDLE, visible=False)
        page.tick(SessionState.IDLE, visible=True)
        assert discovery.refresh_calls == 3

    def test_reopened_profile_reports_populated_input_changes(self) -> None:
        instances = camera_profile().instances
        page = make_page(
            profile=Profile(1, VideoSourceConfiguration(p("first.mp4")), instances)
        )
        page.tick(SessionState.IDLE, visible=True)
        assert page.tick(SessionState.IDLE, visible=True) is False
        profile = Profile(1, VideoSourceConfiguration(p("second.mp4")), instances)
        page._model.open_profile(profile, Path("config.json"))

        assert page.tick(SessionState.IDLE, visible=True) is True
        assert page._source._video_path.value == p("second.mp4")
        assert page.tick(SessionState.IDLE, visible=True) is False

    def test_tab_switch_restores_permissions_after_connection(self) -> None:
        controller = FakeController()
        page = make_page(controller=controller)
        controller.state = SessionState.CONNECTING
        for tab in ProfileTab:
            page.select_tab(tab)
        controller.state = SessionState.RUNNING
        page.select_tab(ProfileTab.INPUT)
        assert page._source._source_type.disabled is False
        page.select_tab(ProfileTab.SCENARIOS)
        assert page._instances._rows[0].rpc.disabled is False

    def test_permissions_and_dirty_state(self) -> None:
        page = make_page()
        assert page.tick(SessionState.IDLE, visible=True) is True
        assert not page._model.is_dirty

        page._model.set_instance_scenario(0, p("other.py"))
        page.tick(SessionState.IDLE, visible=True)
        assert page._model.is_dirty

    def test_transition_state_disables_source_editing(self) -> None:
        page = make_page()
        page.tick(SessionState.IDLE, visible=True)

        page.tick(SessionState.CONNECTING, visible=True)

        assert page._source._source_type.disabled is True

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
        statuses: list[str] = []
        controller = FakeController()
        controller.state = SessionState.RUNNING
        page = make_page(controller=controller, statuses=statuses)
        page.populate()
        page.tick(SessionState.RUNNING, visible=True)

        page._on_input_changed()

        assert statuses == ["Input changed; save to apply."]

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


class TestTabStructure:
    def test_two_tabs_with_input_initial(self) -> None:
        page = make_page()

        content = page._tabs.content
        assert isinstance(content, ft.Column)
        tab_bar = content.controls[0]
        assert isinstance(tab_bar, ft.TabBar)
        labels: list[str] = []
        for tab in tab_bar.tabs:
            assert isinstance(tab, ft.Tab)
            label = tab.label
            assert isinstance(label, str)
            labels.append(label)
        assert labels == [
            "Input",
            "Scenarios & Connections",
        ]
        assert page._tabs.selected_index == 0
        assert page.active_tab is ProfileTab.INPUT

    def test_tab_change_event_selects_tab(self) -> None:
        page = make_page()
        page._tabs.selected_index = 1
        fire(page._on_tab_change, page._tabs)

        assert page.active_tab is ProfileTab.SCENARIOS


class TestInputTab:
    def test_profile_shows_source_and_frame_processing(self) -> None:
        page = make_page()
        page.tick(SessionState.IDLE, visible=True)

        assert page._input._body.visible is True
        assert page._input._empty.visible is False
        labels = collect_text(page._input.control)
        assert "Input source" in labels
        assert "Frame processing" in labels
        assert page.preview.control in collect_controls(page._input.control)

    def test_no_profile_shows_empty_state(self) -> None:
        page = make_page(empty=True)
        page.tick(SessionState.IDLE, visible=True)

        assert page._input._empty.visible is True
        assert page._input._body.visible is False
        assert (
            "Create or open a Profile to configure the input source."
            in collect_text(page._input.control)
        )


class TestPreviewLifecycle:
    def test_input_to_scenarios_stops_and_returning_resyncs(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 1

        page.select_tab(ProfileTab.SCENARIOS)
        asyncio.run(page.pump_preview())
        assert preview.stop_calls >= 1
        stopped = preview.stop_calls

        page.select_tab(ProfileTab.INPUT)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 2
        assert preview.stop_calls == stopped

    def test_scenarios_tab_does_not_schedule_preview(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())
        page.select_tab(ProfileTab.SCENARIOS)
        asyncio.run(page.pump_preview())

        assert len(preview.started) == 1


class TestScenariosTab:
    def test_cards_use_scenario_terminology(self) -> None:
        page = make_page()
        page.tick(SessionState.IDLE, visible=True)
        page.select_tab(ProfileTab.SCENARIOS)

        labels = collect_text(page._scenarios.control)
        assert "Scenarios & Connections" in labels
        assert "Add Scenario" in labels
        assert "Add instance" not in labels
        assert "Scenario 1" in labels
        assert "LiveSplit Connection" in labels
        assert "RPC endpoint" in labels
        assert "Event endpoint" in labels

    def test_edit_add_remove(self) -> None:
        page = make_page()
        page.tick(SessionState.IDLE, visible=True)
        page.select_tab(ProfileTab.SCENARIOS)
        section = page._instances

        section._rows[0].rpc.value = "tcp://127.0.0.1:54000"
        fire(section._rows[0].rpc.on_change, section._rows[0].rpc)
        section._rows[0].event.value = "tcp://127.0.0.1:54001"
        fire(section._rows[0].event.on_change, section._rows[0].event)
        section._rows[0].scenario.value = "next.py"
        fire(section._rows[0].scenario.on_change, section._rows[0].scenario)

        draft = page._model.draft
        assert draft is not None
        assert draft.instances[0].rpc_endpoint == "tcp://127.0.0.1:54000"
        assert draft.instances[0].event_endpoint == "tcp://127.0.0.1:54001"
        assert draft.instances[0].scenario == "next.py"

        fire(section._on_add, section._control)
        assert len(draft.instances) == 2

        section._on_remove(0)
        assert len(draft.instances) == 1

    def test_no_profile_shows_empty_state(self) -> None:
        page = make_page(empty=True)
        page.tick(SessionState.IDLE, visible=True)
        page.select_tab(ProfileTab.SCENARIOS)

        assert page._scenarios._empty.visible is True
        assert page._scenarios._body.visible is False
        assert (
            "Create or open a Profile to configure scenarios and connections."
            in collect_text(page._scenarios.control)
        )
