import threading
from collections.abc import Mapping
from types import TracebackType
from typing import Self

import cv2
import numpy as np
import pytest

from divergencesplitter.frame.capture import (
    CaptureStateMachine,
    LatestFrameBuffer,
    PublishResult,
)
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import FrameNormalizer
from divergencesplitter.frame.source import ErrorAction, FrameSourceState
from divergencesplitter.frame.video_file import VideoFileSource


class FakeError(Exception):
    pass


def make_frame(value: int) -> Frame:
    return Frame(image=np.full((2, 2, 3), value, dtype=np.uint8))


class FakeFrameSource:
    def __init__(
        self,
        *,
        prepare_results: list[FakeError | None],
        read_results: list[Frame | FakeError],
        error_results: list[tuple[ErrorAction, FrameSourceState]],
        raising_stage: str | None = None,
    ) -> None:
        self._state = FrameSourceState.NOT_READY
        self._normalizer = FrameNormalizer()
        self._prepare_results = prepare_results
        self._read_results = read_results
        self._error_results = error_results
        self._raising_stage = raising_stage
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

    def read(self) -> Frame | FakeError:
        self.read_calls += 1
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

    def read(self) -> Frame | FakeError:
        self.read_calls += 1
        self.read_started.set()
        self.release_read.wait(1)
        return make_frame(1)


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, fields: Mapping[str, object]) -> None:
        self.events.append((event, dict(fields)))

    def fields_for(self, event: str) -> list[dict[str, object]]:
        return [fields for name, fields in self.events if name == event]


class RaisingDiagnostics:
    def record(self, event: str, fields: Mapping[str, object]) -> None:
        del event, fields
        raise RuntimeError("diagnostics failed")


class TestLatestFrameBuffer:
    def test_overwrites_unprocessed_frame_and_returns_latest_once(self) -> None:
        buffer = LatestFrameBuffer()
        first = make_frame(1)
        latest = make_frame(2)

        assert buffer.publish(first) is PublishResult.PUBLISHED
        assert buffer.publish(latest) is PublishResult.OVERWROTE

        assert buffer.take(timeout=0) is latest
        assert buffer.take(timeout=0) is None

    def test_stop_releases_waiting_consumer(self) -> None:
        buffer = LatestFrameBuffer()
        results: list[Frame | None] = []
        consumer = threading.Thread(target=lambda: results.append(buffer.take()))
        consumer.start()

        buffer.stop()
        consumer.join(timeout=1)

        assert not consumer.is_alive()
        assert results == [None]

    def test_publish_releases_waiting_consumer(self) -> None:
        buffer = LatestFrameBuffer()
        frame = make_frame(1)
        results: list[Frame | None] = []
        consumer = threading.Thread(target=lambda: results.append(buffer.take()))
        consumer.start()

        assert buffer.publish(frame) is PublishResult.PUBLISHED
        consumer.join(timeout=1)

        assert not consumer.is_alive()
        assert results == [frame]

    def test_stop_delivers_pending_frame_once_and_rejects_new_frames(self) -> None:
        buffer = LatestFrameBuffer()
        pending = make_frame(1)
        assert buffer.publish(pending) is PublishResult.PUBLISHED

        buffer.stop()

        assert buffer.take() is pending
        assert buffer.take() is None
        assert buffer.publish(make_frame(2)) is PublishResult.STOPPED

    def test_rejects_negative_timeout(self) -> None:
        for timeout in (-1, float("nan"), float("inf"), True):
            with pytest.raises(ValueError):
                LatestFrameBuffer().take(timeout=timeout)


class TestCaptureStateMachine:
    def test_prepares_captures_and_stops_on_source_action(self) -> None:
        final_error = FakeError("finished")
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[make_frame(1), make_frame(2), final_error],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
        )
        buffer = LatestFrameBuffer()
        diagnostics = RecordingDiagnostics()
        machine = CaptureStateMachine(source, buffer, diagnostics=diagnostics)

        machine.run()

        latest = buffer.take()
        assert latest is not None
        assert int(latest.image[0, 0, 0]) == 2
        assert buffer.take() is None
        assert [
            fields["publish_result"]
            for fields in diagnostics.fields_for("capture.frame_received")
        ] == ["PUBLISHED", "OVERWROTE"]
        assert source.close_calls == 1
        assert source.state is FrameSourceState.NOT_READY
        assert machine.is_stopped

    def test_retry_uses_source_state_to_prepare_again(self) -> None:
        prepare_error = FakeError("not ready")
        stop_error = FakeError("finished")
        source = FakeFrameSource(
            prepare_results=[prepare_error, None],
            read_results=[make_frame(1), stop_error],
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
        )

        machine.run()

        assert source.prepare_calls == 2
        assert (
            diagnostics.fields_for("capture.error_handled")[0]["error_action"]
            == "RETRY"
        )

    def test_retry_continues_reading_when_source_stays_ready(self) -> None:
        retry_error = FakeError("temporary")
        stop_error = FakeError("finished")
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[retry_error, make_frame(1), stop_error],
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
        )

        machine.run()

        assert source.prepare_calls == 1
        assert source.read_calls == 3
        assert (
            diagnostics.fields_for("capture.error_handled")[0]["error_action"]
            == "RETRY"
        )

    @pytest.mark.parametrize("stage", ["prepare", "read", "handle_error"])
    def test_source_exception_closes_source_and_stops_buffer(self, stage: str) -> None:
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[FakeError("source error")],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
            raising_stage=stage,
        )
        buffer = LatestFrameBuffer()
        machine = CaptureStateMachine(
            source,
            buffer,
            diagnostics=RecordingDiagnostics(),
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

    def test_diagnostics_failure_does_not_stop_capture(self) -> None:
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[make_frame(1), FakeError("finished")],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
        )
        machine = CaptureStateMachine(
            source,
            LatestFrameBuffer(),
            diagnostics=RaisingDiagnostics(),
        )

        machine.run()

        assert source.close_calls == 1

    def test_emits_diagnostics_through_injected_instance(self) -> None:
        source = FakeFrameSource(
            prepare_results=[None],
            read_results=[make_frame(1), make_frame(2), FakeError("finished")],
            error_results=[(ErrorAction.STOP, FrameSourceState.READY)],
        )
        buffer = LatestFrameBuffer()
        diagnostics = RecordingDiagnostics()
        machine = CaptureStateMachine(source, buffer, diagnostics=diagnostics)

        machine.run()

        events = {event for event, _fields in diagnostics.events}
        assert "capture.source_state_changed" in events
        assert "capture.frame_received" in events
        assert "capture.error_handled" in events
        assert "capture.source_closed" in events
        assert "capture.stopped" in events
        assert [
            fields["publish_result"]
            for fields in diagnostics.fields_for("capture.frame_received")
        ] == ["PUBLISHED", "OVERWROTE"]

    def test_rejects_non_positive_retry_delay(self) -> None:
        source = FakeFrameSource(
            prepare_results=[],
            read_results=[],
            error_results=[],
        )
        for delay in (0, -1, float("nan"), float("inf"), True):
            with pytest.raises(ValueError):
                CaptureStateMachine(
                    source,
                    LatestFrameBuffer(),
                    diagnostics=RecordingDiagnostics(),
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
        machine = CaptureStateMachine(source, buffer, diagnostics=diagnostics)

        machine.run()

        latest = buffer.take()
        assert latest is not None
        assert float(latest.image.mean()) > 100
        assert buffer.take() is None
        assert [
            fields["publish_result"]
            for fields in diagnostics.fields_for("capture.frame_received")
        ] == ["PUBLISHED", "OVERWROTE", "OVERWROTE"]
        assert source.state is FrameSourceState.NOT_READY
