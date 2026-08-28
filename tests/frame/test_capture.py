import threading
from types import TracebackType
from typing import Self

import cv2
import numpy as np
import pytest

from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame.capture import (
    CaptureStateMachine,
    LatestFrameBuffer,
    PublishResult,
)
from divergencesplitter.frame.models import CapturedFrame, Frame
from divergencesplitter.frame.normalizer import FrameNormalizer
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameReadResult,
    FrameSourceState,
)
from divergencesplitter.frame.video_file import VideoFileSource


class FakeError(Exception):
    pass


def make_frame(value: int) -> Frame:
    return Frame(image=np.full((2, 2, 3), value, dtype=np.uint8))


def successful_read(value: int) -> FrameReadResult[FakeError]:
    return FrameReadResult(frame=make_frame(value))


def failed_read(error: FakeError) -> FrameReadResult[FakeError]:
    return FrameReadResult(error=error)


def captured_frame(value: int, nanoseconds: int = 0) -> CapturedFrame:
    return CapturedFrame(
        frame=make_frame(value),
        captured_at=MonotonicTime(nanoseconds),
    )


class FixedTimeProvider(TimeProvider):
    def __init__(
        self,
        nanoseconds: int = 123,
        events: list[str] | None = None,
    ) -> None:
        self._now = MonotonicTime(nanoseconds)
        self._events = events
        self.calls = 0

    def now(self) -> MonotonicTime:
        self.calls += 1
        if self._events is not None:
            self._events.append("timestamp")
        return self._now


class FakeFrameSource:
    def __init__(
        self,
        *,
        prepare_results: list[FakeError | None],
        read_results: list[FrameReadResult[FakeError]],
        error_results: list[tuple[ErrorAction, FrameSourceState]],
        raising_stage: str | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._state = FrameSourceState.NOT_READY
        self._normalizer = FrameNormalizer()
        self._prepare_results = prepare_results
        self._read_results = read_results
        self._error_results = error_results
        self._raising_stage = raising_stage
        self._events = events
        self.prepare_calls = 0
        self.read_calls = 0
        self.handle_error_calls = 0
        self.close_calls = 0

    @property
    def state(self) -> FrameSourceState:
        return self._state

    @property
    def normalizer(self) -> FrameNormalizer:
        return self._normalizer

    def prepare(self) -> FakeError | None:
        self.prepare_calls += 1
        if self._raising_stage == "prepare":
            raise RuntimeError("prepare failed")
        result = self._prepare_results.pop(0)
        if result is None:
            self._state = FrameSourceState.READY
        return result

    def read(self) -> FrameReadResult[FakeError]:
        self.read_calls += 1
        if self._events is not None:
            self._events.append("read")
        if self._raising_stage == "read":
            raise RuntimeError("read failed")
        return self._read_results.pop(0)

    def handle_error(self, error: FakeError) -> ErrorAction:
        del error
        self.handle_error_calls += 1
        if self._raising_stage == "handle_error":
            raise RuntimeError("handle_error failed")
        action, state = self._error_results.pop(0)
        self._state = state
        return action

    def close(self) -> None:
        self.close_calls += 1
        self._state = FrameSourceState.NOT_READY

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class BlockingFrameSource(FakeFrameSource):
    def __init__(self) -> None:
        super().__init__(
            prepare_results=[None],
            read_results=[],
            error_results=[],
        )
        self.read_started = threading.Event()
        self.release_read = threading.Event()

    def read(self) -> FrameReadResult[FakeError]:
        self.read_calls += 1
        self.read_started.set()
        self.release_read.wait(1)
        return successful_read(1)


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.preparing_calls = 0
        self.prepared_calls = 0
        self.publish_results: list[PublishResult] = []
        self.source_errors: list[object] = []
        self.handled_errors: list[tuple[ErrorAction, FrameSourceState]] = []
        self.state_changes: list[tuple[FrameSourceState | None, FrameSourceState]] = []
        self.unavailable_errors: list[Exception] = []
        self.source_closed_calls = 0
        self.stopped_calls = 0

    def preparing(self) -> None:
        self.preparing_calls += 1

    def prepared(self) -> None:
        self.prepared_calls += 1

    def frame_received(self, publish_result: PublishResult) -> None:
        self.publish_results.append(publish_result)

    def source_error(self, error: object) -> None:
        self.source_errors.append(error)

    def error_handled(
        self,
        action: ErrorAction,
        state: FrameSourceState,
    ) -> None:
        self.handled_errors.append((action, state))

    def source_state_changed(
        self,
        previous: FrameSourceState | None,
        current: FrameSourceState,
    ) -> None:
        self.state_changes.append((previous, current))

    def source_state_unavailable(self, error: Exception) -> None:
        self.unavailable_errors.append(error)

    def source_closed(self) -> None:
        self.source_closed_calls += 1

    def stopped(self) -> None:
        self.stopped_calls += 1


class TestLatestFrameBuffer:
    def test_overwrites_unprocessed_frame_and_returns_latest_once(self) -> None:
        buffer = LatestFrameBuffer()
        first = captured_frame(1)
        latest = captured_frame(2)

        assert buffer.publish(first) is PublishResult.PUBLISHED
        assert buffer.publish(latest) is PublishResult.OVERWROTE

        assert buffer.take() is latest
        buffer.stop()
        assert buffer.take() is None

    def test_stop_releases_waiting_consumer(self) -> None:
        buffer = LatestFrameBuffer()
        results: list[CapturedFrame | None] = []
        consumer = threading.Thread(target=lambda: results.append(buffer.take()))
        consumer.start()

        buffer.stop()
        consumer.join(timeout=1)

        assert not consumer.is_alive()
        assert results == [None]

    def test_publish_releases_waiting_consumer(self) -> None:
        buffer = LatestFrameBuffer()
        frame = captured_frame(1)
        results: list[CapturedFrame | None] = []
        consumer = threading.Thread(target=lambda: results.append(buffer.take()))
        consumer.start()

        assert buffer.publish(frame) is PublishResult.PUBLISHED
        consumer.join(timeout=1)

        assert not consumer.is_alive()
        assert results == [frame]

    def test_stop_delivers_pending_frame_once_and_rejects_new_frames(self) -> None:
        buffer = LatestFrameBuffer()
        pending = captured_frame(1)
        assert buffer.publish(pending) is PublishResult.PUBLISHED

        buffer.stop()

        assert buffer.take() is pending
        assert buffer.take() is None
        assert buffer.publish(captured_frame(2)) is PublishResult.STOPPED


class TestFrameReadResult:
    def test_requires_exactly_one_frame_or_error(self) -> None:
        with pytest.raises(ValueError):
            FrameReadResult[FakeError]()
        with pytest.raises(ValueError):
            FrameReadResult(frame=make_frame(1), error=FakeError("failure"))


class TestCaptureStateMachine:
    def test_prepares_captures_and_stops_on_source_action(self) -> None:
        final_error = FakeError("finished")
        events: list[str] = []
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[
                successful_read(1),
                successful_read(2),
                failed_read(final_error),
            ],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
            events=events,
        )
        buffer = LatestFrameBuffer()
        diagnostics = RecordingDiagnostics()
        time_provider = FixedTimeProvider(events=events)
        machine = CaptureStateMachine(
            source,
            buffer,
            diagnostics=diagnostics,
            time_provider=time_provider,
        )

        machine.run()

        latest = buffer.take()
        assert latest is not None
        assert int(latest.frame.image[0, 0, 0]) == 2
        assert latest.captured_at == MonotonicTime(123)
        assert time_provider.calls == 2
        assert events == ["read", "timestamp", "read", "timestamp", "read"]
        assert buffer.take() is None
        assert diagnostics.publish_results == [
            PublishResult.PUBLISHED,
            PublishResult.OVERWROTE,
        ]
        assert source.close_calls == 1
        assert source.state is FrameSourceState.NOT_READY
        assert machine.is_stopped

    def test_retry_uses_source_state_to_prepare_again(self) -> None:
        prepare_error = FakeError("not ready")
        stop_error = FakeError("finished")
        source = FakeFrameSource(
            prepare_results=[prepare_error, None],
            read_results=[successful_read(1), failed_read(stop_error)],
            error_results=[
                (ErrorAction.RETRY, FrameSourceState.NOT_READY),
                (ErrorAction.STOP, FrameSourceState.READY),
            ],
        )
        diagnostics = RecordingDiagnostics()
        machine = CaptureStateMachine(
            source,
            LatestFrameBuffer(),
            retry_delay_seconds=0.001,
            diagnostics=diagnostics,
            time_provider=FixedTimeProvider(),
        )

        machine.run()

        assert source.prepare_calls == 2
        assert diagnostics.handled_errors[0][0] is ErrorAction.RETRY

    def test_retry_continues_reading_when_source_stays_ready(self) -> None:
        retry_error = FakeError("temporary")
        stop_error = FakeError("finished")
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[
                failed_read(retry_error),
                successful_read(1),
                failed_read(stop_error),
            ],
            error_results=[
                (ErrorAction.RETRY, FrameSourceState.READY),
                (ErrorAction.STOP, FrameSourceState.READY),
            ],
        )
        diagnostics = RecordingDiagnostics()
        machine = CaptureStateMachine(
            source,
            LatestFrameBuffer(),
            diagnostics=diagnostics,
            time_provider=FixedTimeProvider(),
        )

        machine.run()

        assert source.prepare_calls == 1
        assert source.read_calls == 3
        assert diagnostics.handled_errors[0][0] is ErrorAction.RETRY

    @pytest.mark.parametrize("stage", ["prepare", "read", "handle_error"])
    def test_source_exception_closes_source_and_stops_buffer(self, stage: str) -> None:
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[failed_read(FakeError("source error"))],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
            raising_stage=stage,
        )
        buffer = LatestFrameBuffer()
        machine = CaptureStateMachine(
            source,
            buffer,
            diagnostics=RecordingDiagnostics(),
            time_provider=FixedTimeProvider(),
        )

        with pytest.raises(RuntimeError):
            machine.run()

        assert source.close_calls == 1
        assert buffer.take() is None
        assert machine.is_stopped

    def test_request_stop_releases_consumer_and_closes_after_finite_read(self) -> None:
        source = BlockingFrameSource()
        buffer = LatestFrameBuffer()
        machine = CaptureStateMachine(
            source,
            buffer,
            diagnostics=RecordingDiagnostics(),
            time_provider=FixedTimeProvider(),
        )
        capture = threading.Thread(target=machine.run)
        capture.start()
        assert source.read_started.wait(1)

        machine.request_stop()
        source.release_read.set()
        capture.join(timeout=1)

        assert not capture.is_alive()
        assert buffer.take() is None
        assert source.close_calls == 1

    def test_emits_diagnostics_through_injected_instance(self) -> None:
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[
                successful_read(1),
                successful_read(2),
                failed_read(FakeError("finished")),
            ],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
        )
        buffer = LatestFrameBuffer()
        diagnostics = RecordingDiagnostics()
        machine = CaptureStateMachine(
            source,
            buffer,
            diagnostics=diagnostics,
            time_provider=FixedTimeProvider(),
        )

        machine.run()

        assert diagnostics.preparing_calls == 1
        assert diagnostics.prepared_calls == 1
        assert diagnostics.state_changes == [
            (None, FrameSourceState.NOT_READY),
            (FrameSourceState.NOT_READY, FrameSourceState.READY),
            (FrameSourceState.READY, FrameSourceState.NOT_READY),
        ]
        assert diagnostics.publish_results == [
            PublishResult.PUBLISHED,
            PublishResult.OVERWROTE,
        ]
        assert len(diagnostics.source_errors) == 1
        assert diagnostics.handled_errors == [
            (ErrorAction.STOP, FrameSourceState.READY)
        ]
        assert diagnostics.source_closed_calls == 1
        assert diagnostics.stopped_calls == 1

    def test_rejects_non_positive_retry_delay(self) -> None:
        source = FakeFrameSource(
            prepare_results=[],
            read_results=[],
            error_results=[],
        )
        for delay in (0, -1, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                CaptureStateMachine(
                    source,
                    LatestFrameBuffer(),
                    diagnostics=RecordingDiagnostics(),
                    time_provider=FixedTimeProvider(),
                    retry_delay_seconds=delay,
                )


def make_video(path, frame_count: int, fps: float = 120.0) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore
        fps,
        (16, 16),
    )
    assert writer.isOpened()
    try:
        for index in range(frame_count):
            writer.write(np.full((16, 16, 3), index * 80, dtype=np.uint8))
    finally:
        writer.release()


class TestVideoFileSourceIntegration:
    def test_eof_stops_and_preserves_only_latest_frame(self, tmp_path) -> None:
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=3)
        source = VideoFileSource(str(video))
        buffer = LatestFrameBuffer()
        diagnostics = RecordingDiagnostics()
        machine = CaptureStateMachine(
            source,
            buffer,
            diagnostics=diagnostics,
            time_provider=FixedTimeProvider(),
        )

        machine.run()

        latest = buffer.take()
        assert latest is not None
        assert float(latest.frame.image.mean()) > 100
        assert buffer.take() is None
        assert diagnostics.publish_results == [
            PublishResult.PUBLISHED,
            PublishResult.OVERWROTE,
            PublishResult.OVERWROTE,
        ]
        assert source.state is FrameSourceState.NOT_READY
