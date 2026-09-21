from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from divergencesplitter import LiveSplitConnection
from divergencesplitter.frame.ndi import NdiSupport
from divergencesplitter_runtime.configuration.models import (
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    Profile,
)
from divergencesplitter_ui.configuration.preview import PreviewController
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

    def start(self, path, *, app_settings) -> None:
        if self.state in {
            SessionState.LOADING,
            SessionState.CONNECTING,
            SessionState.RUNNING,
            SessionState.STOPPING,
        }:
            raise SessionAlreadyActiveError(str(path))
        self.state = SessionState.LOADING

    def request_stop(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> bool:
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
        self.join_calls: list[float | None] = []

    def refresh(self) -> None:
        self.refresh_calls += 1

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)

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


def make_model(
    *,
    profile: Profile | None = None,
    empty: bool = False,
    profile_path: Path | None = None,
) -> SettingsModel:
    model = SettingsModel(FakeCameraEnumerator())
    if not empty:
        model.open_profile(
            profile or camera_profile(), profile_path or Path("config.json")
        )
    return model


def make_page(
    *,
    profile: Profile | None = None,
    empty: bool = False,
    profile_path: Path | None = None,
    model: SettingsModel | None = None,
    ndi: FakeNdiDiscovery | None = None,
    controller: FakeController | None = None,
    preview: FakePreviewController | None = None,
    statuses: list[str] | None = None,
) -> ProfilePage:
    actual_model = model or make_model(
        profile=profile, empty=empty, profile_path=profile_path
    )
    recorded = statuses if statuses is not None else []
    return ProfilePage(
        cast(SessionController, controller or FakeController()),
        actual_model,
        FakeDialogs(),
        on_status=recorded.append,
        ndi_discovery=cast(NdiDiscovery, ndi or FakeNdiDiscovery()),
        preview_controller=cast(PreviewController, preview or FakePreviewController()),
    )


class TestPreviewLifecycle:
    def test_visible_input_starts_camera_draft_preview(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())

        assert len(preview.started) == 1
        assert preview.stop_calls == 0
        assert isinstance(preview.started[0], CameraSourceConfiguration)

    def test_non_previewable_source_stops_draft_preview(self) -> None:
        model = make_model()
        preview = FakePreviewController()
        page = make_page(model=model, preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 1
        assert preview.stop_calls == 0

        model.set_source_type(SourceType.VIDEO)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())

        assert len(preview.started) == 1
        assert preview.stop_calls == 1

    def test_active_runtime_does_not_start_draft_preview(self) -> None:
        preview = FakePreviewController()
        controller = FakeController()
        controller.state = SessionState.RUNNING
        page = make_page(preview=preview, controller=controller)

        page.tick(SessionState.RUNNING, visible=True)
        asyncio.run(page.pump_preview())

        assert preview.started == []
        assert preview.stop_calls == 0

    def test_preview_runs_only_while_profile_input_is_visible(self) -> None:
        preview = FakePreviewController()
        page = make_page(preview=preview)
        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 1

        page.tick(SessionState.IDLE, visible=False)
        asyncio.run(page.pump_preview())
        assert preview.stop_calls == 1

        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 2
        assert preview.stop_calls == 1

        page.select_tab(ProfileTab.SCENARIOS)
        asyncio.run(page.pump_preview())
        assert preview.stop_calls == 2

        page.tick(SessionState.IDLE, visible=True)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 2
        assert preview.stop_calls == 2

        page.select_tab(ProfileTab.INPUT)
        asyncio.run(page.pump_preview())
        assert len(preview.started) == 3
        assert preview.stop_calls == 2


class TestPreviewUpdateTargets:
    def test_preview_update_targets_are_limited_to_preview_controls(self) -> None:
        page = make_page()

        targets = page.preview_update_targets()

        assert targets == (page.preview.control, page.input.opened_camera_label)
        assert page.control not in targets


class TestTeardown:
    def test_teardown_stops_preview_and_ndi_worker(self) -> None:
        preview = FakePreviewController()
        ndi = FakeNdiDiscovery()
        page = make_page(preview=preview, ndi=ndi)

        page.teardown()

        assert preview.stop_calls == 1
        assert len(ndi.join_calls) == 1
