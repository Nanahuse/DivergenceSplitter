from typing import ClassVar, get_protocol_members

import cv2
import numpy as np
import pytest
from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame.camera import OpenCvCameraSource
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import (
    ClipRegion,
    FrameNormalizer,
    OutputSize,
)
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSource,
    FrameSourceState,
)

SIZE = (16, 16)


class FixedTimeProvider(TimeProvider):
    def __init__(self, nanoseconds: int) -> None:
        self._now = MonotonicTime(nanoseconds)
        self.calls = 0

    def now(self) -> MonotonicTime:
        self.calls += 1
        return self._now


class FakeVideoCapture:
    instances: ClassVar[list[FakeVideoCapture]] = []

    def __init__(self, device_index: int = 0, backend: int = cv2.CAP_ANY) -> None:
        self.device_index = device_index
        self.backend = backend
        self.opened = True
        self.released = False
        self.set_calls: list[tuple[int, object]] = []
        self.read_results: list[tuple[bool, np.ndarray | None]] = []
        self.read_calls = 0
        FakeVideoCapture.instances.append(self)

    def isOpened(self) -> bool:
        return self.opened

    def release(self) -> None:
        self.released = True
        self.opened = False

    def set(self, prop: int, value: object) -> bool:
        self.set_calls.append((prop, value))
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        self.read_calls += 1
        return self.read_results.pop(0)


class NotOpeningCapture(FakeVideoCapture):
    def isOpened(self) -> bool:
        return False


class FailingSetCapture(FakeVideoCapture):
    def set(self, prop: int, value: object) -> bool:
        self.set_calls.append((prop, value))
        return False


def patch_capture(monkeypatch, capture_cls=FakeVideoCapture) -> list[FakeVideoCapture]:
    FakeVideoCapture.instances = []
    monkeypatch.setattr(cv2, "VideoCapture", capture_cls)
    return FakeVideoCapture.instances


def make_image(width=16, height=16, value=42) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


def read_frame(source: OpenCvCameraSource) -> Frame:
    result = source.read()
    assert isinstance(result, Frame)
    return result


def read_error_action(source: OpenCvCameraSource) -> ErrorAction:
    result = source.read()
    assert not isinstance(result, Frame)
    return source.handle_error(result)


class TestConstruction:
    def test_constructor_accepts_all_arguments(self):
        source = OpenCvCameraSource(
            device_index=2,
            backend=999,
            width=1280,
            height=720,
            fps=30.0,
            clip_region=ClipRegion(x=1, y=2, width=3, height=4),
            output_size=OutputSize(width=10, height=20),
        )
        assert source.state is FrameSourceState.NOT_READY

    def test_default_arguments_are_valid(self):
        source = OpenCvCameraSource()
        assert source.state is FrameSourceState.NOT_READY


class TestValidation:
    @pytest.mark.parametrize("device_index", [-1, -2])
    def test_device_index_must_be_non_negative(self, device_index):
        with pytest.raises(ValueError):
            OpenCvCameraSource(device_index=device_index)

    def test_width_requires_height(self):
        with pytest.raises(ValueError):
            OpenCvCameraSource(width=640)

    def test_height_requires_width(self):
        with pytest.raises(ValueError):
            OpenCvCameraSource(height=480)

    @pytest.mark.parametrize(
        "width,height",
        [(0, 480), (-1, 480), (640, 0), (640, -1)],
    )
    def test_width_and_height_must_be_positive(self, width, height):
        with pytest.raises(ValueError):
            OpenCvCameraSource(width=width, height=height)

    @pytest.mark.parametrize(
        "fps",
        [0.0, -1.0, float("nan"), float("inf"), float("-inf")],
    )
    def test_fps_must_be_finite_and_positive(self, fps):
        with pytest.raises(ValueError):
            OpenCvCameraSource(fps=fps)


class TestPrepare:
    def test_initial_state_is_not_ready(self):
        source = OpenCvCameraSource()
        assert source.state is FrameSourceState.NOT_READY

    def test_prepare_success_moves_to_ready(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY
        assert len(instances) == 1

    def test_prepare_is_idempotent_when_ready(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        assert source.prepare() is None
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY
        assert len(instances) == 1

    def test_prepare_opens_capture_with_device_and_backend(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource(device_index=3, backend=777)
        source.prepare()
        capture = instances[0]
        assert capture.device_index == 3
        assert capture.backend == 777

    def test_open_failure_returns_open_error_and_cleans_up(self, monkeypatch):
        instances = patch_capture(monkeypatch, NotOpeningCapture)
        source = OpenCvCameraSource()
        result = source.prepare()
        assert result is not None
        assert source.handle_error(result) is ErrorAction.RETRY
        assert source.state is FrameSourceState.NOT_READY
        assert instances[0].released

    def test_configuration_failure_returns_config_error_and_cleans_up(
        self, monkeypatch
    ):
        instances = patch_capture(monkeypatch, FailingSetCapture)
        source = OpenCvCameraSource(width=640, height=480, fps=30.0)
        result = source.prepare()
        assert result is not None
        assert source.handle_error(result) is ErrorAction.STOP
        assert source.state is FrameSourceState.NOT_READY
        assert instances[0].released

    def test_properties_are_set_in_width_height_fps_order(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource(width=640, height=480, fps=30.0)
        source.prepare()
        assert instances[0].set_calls == [
            (cv2.CAP_PROP_FRAME_WIDTH, 640),
            (cv2.CAP_PROP_FRAME_HEIGHT, 480),
            (cv2.CAP_PROP_FPS, 30.0),
        ]

    def test_omitted_properties_are_not_set(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        assert instances[0].set_calls == []

    def test_only_configured_properties_are_set(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource(fps=15.0)
        source.prepare()
        assert instances[0].set_calls == [(cv2.CAP_PROP_FPS, 15.0)]


class TestRead:
    def test_read_returns_raw_frame_with_timestamp(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        time_provider = FixedTimeProvider(123)
        source = OpenCvCameraSource(time_provider=time_provider)
        source.prepare()
        instances[0].read_results.append((True, make_image(value=42)))
        result = read_frame(source)
        assert result.image.shape == (*SIZE, 3)
        assert int(result.image[0, 0, 0]) == 42
        assert result.captured_at == MonotonicTime(123)
        assert time_provider.calls == 1

    def test_read_before_ready_is_source_error(self, monkeypatch):
        patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        assert read_error_action(source) is ErrorAction.STOP

    def test_read_after_close_is_source_error(self, monkeypatch):
        patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        source.close()
        assert read_error_action(source) is ErrorAction.STOP

    def test_read_failure_releases_and_returns_read_error(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        capture = instances[0]
        capture.read_results.append((False, None))
        result = source.read()
        assert not isinstance(result, Frame)
        assert source.handle_error(result) is ErrorAction.RETRY
        assert capture.released
        assert source.state is FrameSourceState.NOT_READY

    def test_read_none_image_returns_read_error(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        instances[0].read_results.append((True, None))
        result = source.read()
        assert not isinstance(result, Frame)
        assert source.handle_error(result) is ErrorAction.RETRY
        assert source.state is FrameSourceState.NOT_READY

    def test_retry_after_read_failure_reprepares(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        first = instances[0]
        first.read_results.append((False, None))
        assert read_error_action(source) is ErrorAction.RETRY
        assert source.state is FrameSourceState.NOT_READY
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY
        assert len(instances) == 2
        assert instances[1] is not first


class TestNormalizer:
    def test_normalizer_holds_configured_settings(self):
        region = ClipRegion(x=2, y=3, width=6, height=5)
        size = OutputSize(width=12, height=10)
        source = OpenCvCameraSource(clip_region=region, output_size=size)
        normalizer = source.normalizer
        assert isinstance(normalizer, FrameNormalizer)
        assert normalizer.clip_region == region
        assert normalizer.output_size == size

    def test_default_normalizer_has_no_settings(self):
        source = OpenCvCameraSource()
        assert source.normalizer.clip_region is None
        assert source.normalizer.output_size is None


class TestClose:
    def test_close_releases_capture(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        source.close()
        assert instances[0].released
        assert source.state is FrameSourceState.NOT_READY

    def test_close_is_idempotent(self, monkeypatch):
        patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        source.close()
        source.close()
        assert source.state is FrameSourceState.NOT_READY


class TestContextManager:
    def test_enter_does_not_prepare(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        with source:
            assert source.state is FrameSourceState.NOT_READY
        assert len(instances) == 0

    def test_exit_closes_on_normal_exit(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        with source:
            assert source.state is FrameSourceState.READY
        assert source.state is FrameSourceState.NOT_READY
        assert instances[0].released

    def test_exit_closes_on_exception(self, monkeypatch):
        instances = patch_capture(monkeypatch)
        source = OpenCvCameraSource()
        source.prepare()
        with pytest.raises(RuntimeError), source:
            raise RuntimeError("boom")
        assert source.state is FrameSourceState.NOT_READY
        assert instances[0].released


class TestProtocol:
    def test_camera_source_satisfies_frame_source(self):
        members = get_protocol_members(FrameSource)
        assert "state" in members
        assert "normalizer" in members
        source = OpenCvCameraSource()
        for member in members:
            assert hasattr(source, member), member


class TestExports:
    def test_camera_source_is_exported_from_frame_package(self):
        from divergencesplitter.frame import OpenCvCameraSource

        assert OpenCvCameraSource is not None

    def test_camera_source_is_exported_from_top_level(self):
        import divergencesplitter as ds

        assert ds.OpenCvCameraSource is OpenCvCameraSource

    @pytest.mark.parametrize(
        "name",
        [
            "OpenCvCameraError",
            "OpenCvCameraOpenError",
            "OpenCvCameraConfigurationError",
            "OpenCvCameraReadError",
            "OpenCvCameraReadBeforeReadyError",
        ],
    )
    def test_camera_errors_are_not_reexported(self, name):
        import divergencesplitter as ds
        import divergencesplitter.frame as frame_api

        assert not hasattr(ds, name)
        assert not hasattr(frame_api, name)
