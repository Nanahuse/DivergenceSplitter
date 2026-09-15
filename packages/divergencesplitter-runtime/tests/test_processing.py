"""Frame dispatcher: normalization, latest shared frame publish, diagnostics."""

import threading

import numpy as np
from divergencesplitter import (
    ClipRegion,
    Frame,
    FrameNormalizationError,
    FrameNormalizer,
    MonotonicTime,
    OutputSize,
)
from divergencesplitter.clock import TimeProvider
from divergencesplitter.frame.models import FrameContext, SharedFrameEvaluation
from divergencesplitter_runtime import LatestFrameBuffer, ProcessingRuntime


def frame(captured_at: int = 10) -> Frame:
    return Frame(
        image=np.arange(16, dtype=np.uint8).reshape((4, 4)),
        captured_at=MonotonicTime(captured_at),
    )


class FakeTimeProvider(TimeProvider):
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> MonotonicTime:
        self.calls += 1
        return MonotonicTime(20)


class RecordingInstance:
    def __init__(self) -> None:
        self.frames: list[SharedFrameEvaluation] = []

    def publish_frame(self, shared: SharedFrameEvaluation) -> None:
        self.frames.append(shared)


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.started: list[tuple[Frame, MonotonicTime]] = []
        self.normalization_errors: list[FrameNormalizationError] = []
        self.completed: list[FrameContext] = []
        self.frame_started = threading.Event()
        self.normalization_failed = threading.Event()

    def frame_processing_started(
        self, frame: Frame, processing_started_at: MonotonicTime
    ) -> None:
        self.started.append((frame, processing_started_at))
        self.frame_started.set()

    def frame_normalization_failed(self, error: FrameNormalizationError) -> None:
        self.normalization_errors.append(error)
        self.normalization_failed.set()

    def frame_processing_completed(self, context: FrameContext) -> None:
        self.completed.append(context)


class RecordingNormalizer(FrameNormalizer):
    def __init__(
        self,
        *,
        clip_region: ClipRegion | None = None,
        output_size: OutputSize | None = None,
    ) -> None:
        super().__init__(clip_region=clip_region, output_size=output_size)
        self.frames: list[Frame] = []

    def normalize(self, frame: Frame) -> Frame | FrameNormalizationError:
        self.frames.append(frame)
        return super().normalize(frame)


def process_one_frame(
    runtime: ProcessingRuntime,
    diagnostics: RecordingDiagnostics,
) -> None:
    thread = threading.Thread(target=runtime.run)
    thread.start()
    assert diagnostics.frame_started.wait(1)
    runtime.request_stop()
    thread.join(1)
    assert not thread.is_alive()


def test_dispatches_one_shared_frame_to_every_instance_and_reads_clock_once() -> None:
    first, second = RecordingInstance(), RecordingInstance()
    buffer = LatestFrameBuffer()
    pending = frame()
    buffer.publish(pending)
    clock = FakeTimeProvider()
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (first, second),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=clock,
    )

    process_one_frame(runtime, diagnostics)

    assert clock.calls == 1
    assert len(first.frames) == 1
    assert first.frames[0] is second.frames[0]
    assert first.frames[0].now == MonotonicTime(20)
    assert [context.shared for context in diagnostics.completed] == [first.frames[0]]
    assert diagnostics.started == [(pending, MonotonicTime(20))]


def test_normalizes_frame_once_before_publish() -> None:
    instance = RecordingInstance()
    buffer = LatestFrameBuffer()
    pending = frame()
    buffer.publish(pending)
    normalizer = RecordingNormalizer(
        clip_region=ClipRegion(x=1, y=1, width=2, height=2),
        output_size=OutputSize(width=1, height=1),
    )
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance,),
        buffer,
        normalizer,
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )

    process_one_frame(runtime, diagnostics)

    assert normalizer.frames == [pending]
    assert len(instance.frames) == 1
    dispatched = instance.frames[0].frame
    assert dispatched.image.shape == (1, 1)
    assert dispatched.captured_at == pending.captured_at


def test_normalization_failure_stops_without_publishing_a_frame() -> None:
    instance = RecordingInstance()
    buffer = LatestFrameBuffer()
    buffer.publish(frame())
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance,),
        buffer,
        FrameNormalizer(clip_region=ClipRegion(x=0, y=0, width=99, height=99)),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )
    thread = threading.Thread(target=runtime.run)

    thread.start()
    assert diagnostics.normalization_failed.wait(1)
    thread.join(1)

    assert not thread.is_alive()
    assert instance.frames == []
    assert len(diagnostics.normalization_errors) == 1


def test_stop_without_frames_exits_cleanly() -> None:
    instance = RecordingInstance()
    buffer = LatestFrameBuffer()
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance,),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )
    thread = threading.Thread(target=runtime.run)

    thread.start()
    runtime.request_stop()
    thread.join(1)

    assert not thread.is_alive()
    assert instance.frames == []
