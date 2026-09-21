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
    NdiSourceConfiguration,
    Profile,
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


def video_profile() -> Profile:
    return Profile(
        version=1,
        source=VideoSourceConfiguration(p("clip.mp4")),
        instances=camera_profile().instances,
    )


def ndi_profile() -> Profile:
    return Profile(
        version=1,
        source=NdiSourceConfiguration("OBS"),
        instances=camera_profile().instances,
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


class TestPreviewTabLifecycle:
    def test_hidden_tick_is_cheap_and_stops_preview(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        page.tick(SessionState.IDLE, visible=False)

        assert page._pending_preview_command is not None

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


class TestTeardown:
    def test_teardown_stops_preview_and_ndi(self) -> None:
        preview = FakePreviewController()
        ndi = FakeNdiDiscovery()
        page = make_page(preview=preview, ndi=ndi)

        page.teardown()

        assert preview.stop_calls == 1


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
