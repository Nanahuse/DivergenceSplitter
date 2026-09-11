from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest
from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame import ndi
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.ndi import (
    NdiError,
    NdiInitializationError,
    NdiNoFrameError,
    NdiReadBeforeReadyError,
    NdiReceiveError,
    NdiReceiverCreationError,
    NdiSource,
    NdiSourceNotFoundError,
    NdiUnavailableError,
    NdiVideoFrame,
)
from divergencesplitter.frame.source import ErrorAction, FrameSourceState


class FixedTimeProvider(TimeProvider):
    def __init__(self, nanoseconds: int) -> None:
        self._now = MonotonicTime(nanoseconds)

    def now(self) -> MonotonicTime:
        return self._now


def frame_image(width: int = 6, height: int = 4) -> np.ndarray:
    return np.arange(width * height * 3, dtype=np.uint8).reshape(height, width, 3)


class FakeNdiApi:
    """A configurable NDI boundary double for ``NdiSource`` tests."""

    def __init__(self, *, sources: Sequence[str] = ()) -> None:
        self.sources = tuple(sources)
        self.outcomes: list[object] = []
        self.open_error: NdiError | None = None
        self.destroyed = 0
        self.closed = 0

    def open_receiver(self, source_name: str) -> object:
        if self.open_error is not None:
            raise self.open_error
        if source_name not in self.sources:
            raise NdiSourceNotFoundError(f"missing: {source_name!r}")
        return object()

    def receive_video(self, receiver: object, timeout_ms: int) -> NdiVideoFrame | None:
        if not self.outcomes:
            return None
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, NdiError):
            raise outcome
        if outcome is None:
            return None
        assert isinstance(outcome, NdiVideoFrame)
        return outcome

    def destroy_receiver(self, receiver: object) -> None:
        self.destroyed += 1

    def close(self) -> None:
        self.closed += 1


class FakeVideo:
    def __init__(self, data: np.ndarray) -> None:
        self.data = data
        self.xres = data.shape[1]
        self.yres = data.shape[0]


class FakeNdiSourceHandle:
    def __init__(self, name: str) -> None:
        self.ndi_name = name


class FakeNdiModule:
    """A minimal ``NDIlib`` module double."""

    FRAME_TYPE_VIDEO = 1
    FRAME_TYPE_ERROR = 4
    RECV_COLOR_FORMAT_BGRX_BGRA = 100

    def __init__(
        self,
        *,
        source_names: Sequence[str] = (),
        video: FakeVideo | None = None,
        initialize_ok: bool = True,
        receiver_created: bool = True,
    ) -> None:
        self.source_names = list(source_names)
        self.video = video
        self.initialize_ok = initialize_ok
        self.receiver_created = receiver_created
        self.initialized = False
        self.destroyed = 0
        self.freed = False
        self.recv_error = False
        self.connected: list[str] = []

    def initialize(self) -> bool:
        self.initialized = self.initialize_ok
        return self.initialize_ok

    def destroy(self) -> None:
        self.destroyed += 1
        self.initialized = False

    def find_create_v2(self) -> object:
        return object()

    def find_wait_for_sources(self, finder: object, timeout_ms: int) -> bool:
        return True

    def find_get_current_sources(self, finder: object) -> list[FakeNdiSourceHandle]:
        return [FakeNdiSourceHandle(name) for name in self.source_names]

    def find_destroy(self, finder: object) -> None:
        return None

    class _RecvCreate:
        color_format: object = None

    def RecvCreateV3(self) -> object:
        return FakeNdiModule._RecvCreate()

    def recv_create_v3(self, create: object) -> object | None:
        return object() if self.receiver_created else None

    def recv_connect(self, receiver: object, source: FakeNdiSourceHandle) -> None:
        self.connected.append(source.ndi_name)

    def recv_capture_v2(
        self,
        receiver: object,
        timeout_ms: int,
        want_audio: bool = False,
        want_metadata: bool = False,
    ) -> tuple[object, object, object, object]:
        if self.recv_error:
            return (self.FRAME_TYPE_ERROR, None, None, None)
        if self.video is None:
            return (0, None, None, None)
        return (self.FRAME_TYPE_VIDEO, self.video, None, None)

    def recv_free_video_v2(self, receiver: object, video: FakeVideo) -> None:
        self.freed = True
        video.data[:] = 255


def install_fake_module(monkeypatch, module: FakeNdiModule) -> None:
    monkeypatch.setattr(ndi, "_runtime", ndi._NdiGlobal())
    monkeypatch.setattr(ndi.importlib, "import_module", lambda name: module)


class TestNdiSupport:
    def test_unavailable_when_binding_is_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(ndi, "_runtime", ndi._NdiGlobal())

        def missing(name: str) -> object:
            raise ModuleNotFoundError(name)

        monkeypatch.setattr(ndi.importlib, "import_module", missing)

        support = ndi.detect_ndi_support()

        assert support.available is False
        assert support.reason is not None

    def test_unavailable_when_initialization_fails(self, monkeypatch) -> None:
        module = FakeNdiModule(initialize_ok=False)
        install_fake_module(monkeypatch, module)

        support = ndi.detect_ndi_support()

        assert support.available is False
        assert module.initialized is False

    def test_available_when_initialization_succeeds_then_releases(
        self, monkeypatch
    ) -> None:
        module = FakeNdiModule()
        install_fake_module(monkeypatch, module)

        support = ndi.detect_ndi_support()

        assert support.available is True
        assert module.initialized is False


class TestDiscovery:
    def test_returns_advertised_source_names(self, monkeypatch) -> None:
        module = FakeNdiModule(source_names=("Gaming PC (OBS)", "Laptop"))
        install_fake_module(monkeypatch, module)

        assert ndi.discover_ndi_sources(0) == ("Gaming PC (OBS)", "Laptop")

    def test_unavailable_binding_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(ndi, "_runtime", ndi._NdiGlobal())

        def missing(name: str) -> object:
            raise ModuleNotFoundError(name)

        monkeypatch.setattr(ndi.importlib, "import_module", missing)

        with pytest.raises(NdiUnavailableError):
            ndi.discover_ndi_sources(0)

    def test_rejects_negative_timeout(self) -> None:
        with pytest.raises(ValueError):
            ndi.discover_ndi_sources(-1)


class TestNdiModuleApi:
    def test_open_receiver_missing_source_raises(self, monkeypatch) -> None:
        module = FakeNdiModule(source_names=())
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        with pytest.raises(NdiSourceNotFoundError):
            api.open_receiver("Gaming PC (OBS)")
        api.close()

    def test_open_receiver_creation_failure_raises(self, monkeypatch) -> None:
        module = FakeNdiModule(
            source_names=("Gaming PC (OBS)",), receiver_created=False
        )
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        with pytest.raises(NdiReceiverCreationError):
            api.open_receiver("Gaming PC (OBS)")
        api.close()

    def test_open_receiver_connects_named_source(self, monkeypatch) -> None:
        module = FakeNdiModule(source_names=("Gaming PC (OBS)",))
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        api.open_receiver("Gaming PC (OBS)")

        assert module.connected == ["Gaming PC (OBS)"]
        api.close()

    def test_received_video_survives_buffer_free(self, monkeypatch) -> None:
        buffer = np.arange(4 * 6 * 4, dtype=np.uint8).reshape(4, 6, 4)
        module = FakeNdiModule(video=FakeVideo(buffer))
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        received = api.receive_video(object(), 100)

        assert received is not None
        expected = (np.arange(4 * 6 * 4, dtype=np.uint8).reshape(4, 6, 4))[:, :, :3]
        assert module.freed is True
        assert int(buffer.max()) == 255
        np.testing.assert_array_equal(received.image, expected)
        api.close()

    def test_receive_error_is_reported(self, monkeypatch) -> None:
        module = FakeNdiModule()
        module.recv_error = True
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        with pytest.raises(NdiReceiveError):
            api.receive_video(object(), 100)
        api.close()

    def test_timeout_returns_none(self, monkeypatch) -> None:
        module = FakeNdiModule(video=None)
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        assert api.receive_video(object(), 100) is None
        api.close()

    def test_close_is_idempotent(self, monkeypatch) -> None:
        module = FakeNdiModule()
        install_fake_module(monkeypatch, module)
        api = ndi.NdiModuleApi()

        api.close()
        api.close()

        assert module.initialized is False


class TestNdiSource:
    def test_prepare_missing_source_is_retryable(self) -> None:
        source = NdiSource("Gaming PC (OBS)", api=FakeNdiApi(sources=()))

        error = source.prepare()

        assert isinstance(error, NdiSourceNotFoundError)
        assert source.state is FrameSourceState.NOT_READY
        assert source.handle_error(error) is ErrorAction.RETRY

    def test_prepare_unavailable_stops(self) -> None:
        api = FakeNdiApi()
        api.open_error = NdiUnavailableError("NDI is not installed")
        source = NdiSource("Gaming PC (OBS)", api=api)

        error = source.prepare()

        assert isinstance(error, NdiUnavailableError)
        assert source.state is FrameSourceState.NOT_READY
        assert source.handle_error(error) is ErrorAction.STOP

    def test_prepare_initialization_failure_stops(self) -> None:
        api = FakeNdiApi()
        api.open_error = NdiInitializationError("cannot initialize")
        source = NdiSource("Gaming PC (OBS)", api=api)

        error = source.prepare()

        assert isinstance(error, NdiInitializationError)
        assert source.handle_error(error) is ErrorAction.STOP

    def test_prepare_success_moves_to_ready(self) -> None:
        source = NdiSource(
            "Gaming PC (OBS)", api=FakeNdiApi(sources=("Gaming PC (OBS)",))
        )

        assert source.prepare() is None
        assert source.state is FrameSourceState.READY

    def test_read_before_ready_is_error(self) -> None:
        source = NdiSource(
            "Gaming PC (OBS)", api=FakeNdiApi(sources=("Gaming PC (OBS)",))
        )

        error = source.read()

        assert isinstance(error, NdiReadBeforeReadyError)
        assert source.handle_error(error) is ErrorAction.STOP

    def test_read_returns_bgr_frame_with_provider_time(self) -> None:
        image = frame_image()
        api = FakeNdiApi(sources=("Gaming PC (OBS)",))
        api.outcomes = [NdiVideoFrame(image)]
        source = NdiSource(
            "Gaming PC (OBS)",
            api=api,
            time_provider=FixedTimeProvider(777),
        )
        assert source.prepare() is None

        result = source.read()

        assert isinstance(result, Frame)
        assert result.image.shape == (4, 6, 3)
        assert result.image.dtype == np.uint8
        assert result.captured_at == MonotonicTime(777)
        assert source.resolution == (6, 4)

    def test_read_timeout_is_not_fatal_and_keeps_receiver(self) -> None:
        api = FakeNdiApi(sources=("Gaming PC (OBS)",))
        api.outcomes = [None, NdiVideoFrame(frame_image())]
        source = NdiSource("Gaming PC (OBS)", api=api)
        assert source.prepare() is None

        error = source.read()

        assert isinstance(error, NdiNoFrameError)
        assert source.handle_error(error) is ErrorAction.RETRY
        assert source.state is FrameSourceState.READY
        assert api.destroyed == 0
        assert isinstance(source.read(), Frame)

    def test_sender_disconnect_then_recovery_reuses_receiver(self) -> None:
        api = FakeNdiApi(sources=("Gaming PC (OBS)",))
        api.outcomes = [None, None, NdiVideoFrame(frame_image())]
        source = NdiSource("Gaming PC (OBS)", api=api)
        assert source.prepare() is None

        assert isinstance(source.read(), NdiNoFrameError)
        assert isinstance(source.read(), NdiNoFrameError)
        assert source.state is FrameSourceState.READY
        assert api.destroyed == 0
        assert isinstance(source.read(), Frame)

    def test_receive_error_recreates_receiver_on_prepare(self) -> None:
        api = FakeNdiApi(sources=("Gaming PC (OBS)",))
        api.outcomes = [NdiReceiveError("temporary failure")]
        source = NdiSource("Gaming PC (OBS)", api=api)
        assert source.prepare() is None

        error = source.read()

        assert isinstance(error, NdiReceiveError)
        assert source.handle_error(error) is ErrorAction.RETRY
        assert source.state is FrameSourceState.NOT_READY
        assert api.destroyed == 1
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY

    def test_close_releases_receiver_and_is_idempotent(self) -> None:
        api = FakeNdiApi(sources=("Gaming PC (OBS)",))
        source = NdiSource("Gaming PC (OBS)", api=api)
        assert source.prepare() is None

        source.close()
        source.close()

        assert api.destroyed == 1
        assert source.state is FrameSourceState.NOT_READY

    def test_output_size_is_applied_by_normalizer(self) -> None:
        from divergencesplitter.frame.normalizer import OutputSize

        image = frame_image(8, 6)
        api = FakeNdiApi(sources=("Gaming PC (OBS)",))
        api.outcomes = [NdiVideoFrame(image)]
        source = NdiSource(
            "Gaming PC (OBS)",
            output_size=OutputSize(width=12, height=10),
            api=api,
        )
        assert source.prepare() is None

        result = source.read()

        assert isinstance(result, Frame)
        normalized = source.normalizer.normalize(result)
        assert isinstance(normalized, Frame)
        assert normalized.image.shape == (10, 12, 3)

    def test_rejects_empty_source_name(self) -> None:
        with pytest.raises(ValueError):
            NdiSource("")

    def test_rejects_non_positive_receive_timeout(self) -> None:
        with pytest.raises(ValueError):
            NdiSource("Gaming PC (OBS)", receive_timeout_ms=0)
