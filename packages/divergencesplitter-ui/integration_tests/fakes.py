"""Test doubles for the Flet UI integration suite.

Only the external boundaries are faked: the session/runtime construction path,
camera enumeration, NDI discovery, the draft preview, and the native file
dialogs. The UI components, the ``SettingsModel``, the presentation functions,
and the Flet controls all stay real, so an integration test still exercises the
actual event and synchronization flow.

These doubles are deliberately exercised through their public API (for example
``FakeDiagnostics.instances_changed``) instead of poking private production
state, so a test never has to bypass the component under test.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from typing import cast

from divergencesplitter import (
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    Scenario,
    VideoFileSource,
)
from divergencesplitter_runtime.configuration.models import (
    AppSettings,
    InstanceConfiguration,
    Profile,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_ui.ndi_discovery import NdiSupport
from divergencesplitter_ui.settings import CameraDevice


def sample_profile(
    *,
    video_path: Path,
    scenario_path: Path,
    rpc_endpoint: str = "tcp://127.0.0.1:54000",
    event_endpoint: str = "tcp://127.0.0.1:54001",
) -> Profile:
    """Build a valid single-instance video Profile at absolute paths."""

    return Profile(
        version=1,
        source=VideoSourceConfiguration(str(video_path)),
        instances=(
            InstanceConfiguration(
                LiveSplitConnection(rpc_endpoint, event_endpoint),
                str(scenario_path),
            ),
        ),
    )


class FakeDialogs:
    """A queue-backed ``FileDialogs`` double the test can steer per call."""

    def __init__(
        self,
        *,
        open_results: Sequence[Path | None] = (),
        save_results: Sequence[Path | None] = (),
    ) -> None:
        self.open_results = list(open_results)
        self.save_results = list(save_results)
        self.open_calls = 0
        self.save_calls = 0
        self.confirm_discard_calls = 0
        self.confirm_discard_result = True

    def queue_open(self, *paths: Path | None) -> None:
        self.open_results.extend(paths)

    async def open_file(self, **kwargs: object) -> Path | None:
        self.open_calls += 1
        return self.open_results.pop(0) if self.open_results else None

    async def save_file(self, **kwargs: object) -> Path | None:
        self.save_calls += 1
        return self.save_results.pop(0) if self.save_results else None

    async def confirm_discard(self) -> bool:
        self.confirm_discard_calls += 1
        return self.confirm_discard_result


class FakeCameraEnumerator:
    """One deterministic DirectShow camera so the Settings model is usable."""

    def list_devices(self) -> Sequence[CameraDevice]:
        from types import SimpleNamespace

        return cast(
            "Sequence[CameraDevice]",
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=7,
                    modes=[
                        SimpleNamespace(
                            width=1280, height=720, fps=60.0, subtype_guid="MJPG"
                        ),
                    ],
                )
            ],
        )


class FakeNdiDiscovery:
    """A stable NDI surface; no receiver or discovery worker is ever started."""

    def __init__(
        self, *, available: bool = False, sources: tuple[str, ...] = ()
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
    """The draft preview boundary without opening a camera, NDI, or video file."""

    def __init__(self) -> None:
        self.started: list[object] = []
        self.stop_calls = 0
        self.transforms: list[object] = []

    def update_transform(self, transform: object) -> None:
        self.transforms.append(transform)

    def start_draft(self, configuration: object) -> None:
        self.started.append(configuration)

    def stop(self) -> None:
        self.stop_calls += 1

    def take_frame(self) -> None:
        return None

    def normalize(self, frame: object) -> object:
        return frame

    @property
    def capture_settings(self) -> None:
        return None

    @property
    def error(self) -> None:
        return None


class FakeProfileLoader:
    def __init__(self, *, profile: Profile, error: BaseException | None = None) -> None:
        self._profile = profile
        self._error = error
        self.loaded_paths: list[Path] = []

    def load(self, path: Path) -> Profile:
        self.loaded_paths.append(path)
        if self._error is not None:
            raise self._error
        return self._profile


class FakeScenarioLoader:
    def __init__(
        self, *, scenario: Scenario | None = None, error: BaseException | None = None
    ) -> None:
        self._scenario = scenario or Scenario(
            start_condition=Detected(MeanBrightnessDetector(), -1.0),
            reset_condition=Detected(MeanBrightnessDetector(), -1.0),
            incomplete_condition=None,
            splits=(),
        )
        self._error = error
        self.loaded_paths: list[Path] = []

    def load(self, path: Path) -> Scenario:
        self.loaded_paths.append(path)
        if self._error is not None:
            raise self._error
        return self._scenario


class FakeSourceBuilder:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self._error = error
        self.built: list[object] = []

    def build(self, configuration: object) -> VideoFileSource:
        self.built.append(configuration)
        if self._error is not None:
            raise self._error
        return VideoFileSource("recording.mp4")


class FakeDiagnostics(OperationalDiagnostics):
    """Real diagnostics with a test-controlled instance status channel.

    ``instances_changed`` is the public seam the runtime uses to publish status,
    so a test drives CONNECTING/READY/FAILED changes through it and the whole
    Session-to-Monitor path runs unchanged.
    """

    def __init__(self) -> None:
        super().__init__(StringIO())
        self._started = threading.Event()
        self.set_level_calls: list[int] = []
        self.bind_runtime_calls: list[object] = []
        self.runtime_started_calls = 0

    def set_level(self, level: int) -> None:
        self.set_level_calls.append(level)

    def bind_runtime(self, instances, frame_source) -> None:
        self.bind_runtime_calls.append((instances, frame_source))
        super().bind_runtime(instances, frame_source)
        self.instances_changed(
            tuple(
                InstanceStatus(i, InstanceRuntimeState.CONNECTING)
                for i in range(len(instances))
            )
        )

    def runtime_started(self) -> None:
        self.runtime_started_calls += 1
        self._started.set()

    def is_runtime_started(self) -> bool:
        return self._started.is_set()


class FakeDiagnosticsFactory:
    def __init__(self) -> None:
        self.created: list[FakeDiagnostics] = []

    def create(self) -> FakeDiagnostics:
        diagnostics = FakeDiagnostics()
        self.created.append(diagnostics)
        return diagnostics

    @property
    def latest(self) -> FakeDiagnostics:
        return self.created[-1]


class FakeRuntime:
    """A runtime that reaches READY and optionally blocks until stopped."""

    def __init__(
        self,
        diagnostics: FakeDiagnostics,
        *,
        call_runtime_started: bool = True,
        release_on_run: bool = False,
    ) -> None:
        self._diagnostics = diagnostics
        self._call_runtime_started = call_runtime_started
        self._release_on_run = release_on_run
        self.ran = threading.Event()
        self._release = threading.Event()
        self.request_stop_calls = 0
        self.request_reset_all_calls = 0

    def request_stop(self) -> None:
        self.request_stop_calls += 1
        self._release.set()

    def request_reset_all(self) -> None:
        self.request_reset_all_calls += 1

    def release(self) -> None:
        self._release.set()

    def run(self) -> None:
        self.ran.set()
        if self._call_runtime_started:
            self._diagnostics.runtime_started()
            self.publish_ready()
        if not self._release_on_run:
            self._release.wait()

    def publish_connecting(self) -> None:
        self._diagnostics.instances_changed(
            tuple(
                InstanceStatus(status.scenario_index, InstanceRuntimeState.CONNECTING)
                for status in self._diagnostics.instance_statuses()
            )
        )

    def publish_ready(self) -> None:
        self._diagnostics.instances_changed(
            tuple(
                InstanceStatus(status.scenario_index, InstanceRuntimeState.READY)
                for status in self._diagnostics.instance_statuses()
            )
        )


class FakeRuntimeFactory:
    def __init__(
        self, *, release_on_run: bool = False, call_runtime_started: bool = True
    ) -> None:
        self.release_on_run = release_on_run
        self.call_runtime_started = call_runtime_started
        self.runtimes: list[FakeRuntime] = []
        self.reaction_time_ms = 0

    def create(
        self, instances, frame_source, *, diagnostics, reaction_time_ms=0
    ) -> FakeRuntime:
        self.reaction_time_ms = reaction_time_ms
        runtime = FakeRuntime(
            diagnostics,
            call_runtime_started=self.call_runtime_started,
            release_on_run=self.release_on_run,
        )
        self.runtimes.append(runtime)
        return runtime


DEFAULT_APP_SETTINGS = AppSettings(version=1, log_level="OFF", reaction_time_ms=0)
