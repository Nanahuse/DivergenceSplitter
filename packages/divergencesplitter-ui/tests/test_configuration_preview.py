from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import numpy as np
from divergencesplitter import Frame, MonotonicTime
from divergencesplitter.frame.camera import CameraCaptureSettings
from divergencesplitter.frame.normalizer import FrameNormalizationError
from divergencesplitter_runtime.configuration.models import (
    CameraSourceConfiguration,
    NdiSourceConfiguration,
    SourceTransformConfiguration,
)
from divergencesplitter_ui.camera_preview import CameraPreview
from divergencesplitter_ui.configuration.preview import (
    ConfigurationPreview,
    PreviewController,
    capture_settings_label,
)


class FakeCameraPreview:
    def __init__(self) -> None:
        self.started: list[CameraSourceConfiguration | NdiSourceConfiguration] = []
        self.stop_calls = 0
        self.transforms: list = []
        self.latest: Frame | None = None
        self.normalized: object | None = None
        self.error: str | None = None
        self.settings = None

    def start(self, configuration) -> None:
        self.started.append(configuration)

    def stop(self) -> None:
        self.stop_calls += 1

    def update_transform(self, transform) -> None:
        self.transforms.append(transform)

    def take_latest(self) -> Frame | None:
        return self.latest

    def normalize_frame(self, frame):
        return frame if self.normalized is None else self.normalized

    @property
    def capture_settings(self):
        return self.settings


def make_frame(value: int) -> Frame:
    return Frame(
        np.full((2, 2, 3), value, dtype=np.uint8),
        MonotonicTime(value),
    )


def make_controller(
    camera: FakeCameraPreview,
    *,
    runtime_frame=None,
    runtime_active: bool = False,
) -> PreviewController:
    return PreviewController(
        camera_preview=cast(CameraPreview, camera),
        runtime_frame_provider=lambda: runtime_frame,
        runtime_active=lambda: runtime_active,
    )


class TestPreviewController:
    def test_draft_frame_when_runtime_inactive(self) -> None:
        camera = FakeCameraPreview()
        camera.latest = make_frame(1)
        controller = make_controller(camera)

        assert controller.take_frame() is camera.latest

    def test_runtime_frame_when_active(self) -> None:
        camera = FakeCameraPreview()
        camera.latest = make_frame(1)
        runtime = make_frame(2)
        controller = make_controller(camera, runtime_frame=runtime, runtime_active=True)

        assert controller.take_frame() is runtime

    def test_start_stop_transform_and_normalize_are_forwarded(self) -> None:
        camera = FakeCameraPreview()
        controller = make_controller(camera)
        configuration = NdiSourceConfiguration("OBS")

        controller.start_draft(configuration)
        controller.update_transform(SourceTransformConfiguration())
        controller.stop()

        assert camera.started == [configuration]
        assert len(camera.transforms) == 1
        assert camera.stop_calls == 1

    def test_normalize_delegates_to_camera_preview(self) -> None:
        camera = FakeCameraPreview()
        camera.normalized = FrameNormalizationError("bad")
        controller = make_controller(camera)

        result = controller.normalize(make_frame(1))

        assert isinstance(result, FrameNormalizationError)


class TestCaptureSettingsLabel:
    def test_none_is_dash(self) -> None:
        assert capture_settings_label(None) == "Opened camera: —"

    def test_settings_are_formatted(self) -> None:
        settings = cast(
            CameraCaptureSettings,
            SimpleNamespace(width=1280, height=720, fps=59.94),
        )

        assert capture_settings_label(settings) == "Opened camera: 1280×720 @ 59.94 FPS"


class TestConfigurationPreviewPump:
    def test_no_frame_is_not_a_change(self) -> None:
        camera = FakeCameraPreview()
        preview = ConfigurationPreview()

        assert asyncio.run(preview.pump(make_controller(camera))) is False

    def test_normalization_error_sets_status_once(self) -> None:
        camera = FakeCameraPreview()
        camera.latest = make_frame(1)
        camera.normalized = FrameNormalizationError("bad frame")
        preview = ConfigurationPreview()
        controller = make_controller(camera)

        assert asyncio.run(preview.pump(controller)) is True
        assert asyncio.run(preview.pump(controller)) is False


class TestSourceSwitch:
    def test_switching_draft_source_stops_before_starting(self) -> None:
        camera = FakeCameraPreview()
        controller = make_controller(camera)

        controller.start_draft(NdiSourceConfiguration("A"))
        controller.stop()
        controller.start_draft(NdiSourceConfiguration("B"))

        assert [cast(NdiSourceConfiguration, item).name for item in camera.started] == [
            "A",
            "B",
        ]
        assert camera.stop_calls == 1
