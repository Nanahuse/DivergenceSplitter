"""Frame dispatcher that normalizes frames and hands them to each instance.

Scenario evaluation no longer happens here. Each :class:`InstanceRuntime`
evaluates the shared frame on its own thread; the dispatcher only owns the
capture-to-frame pipeline and the latest-only frame slot handoff.
"""

import threading
from typing import Protocol

from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame.models import Frame, FrameContext, SharedFrameEvaluation
from divergencesplitter.frame.normalizer import (
    FrameNormalizationError,
    FrameNormalizer,
)

from divergencesplitter_runtime.capture import LatestFrameBuffer

DEFAULT_FRAME_WAIT_SECONDS = 0.05


class FrameSink(Protocol):
    """Receives the newest shared frame; implemented by InstanceRuntime."""

    def publish_frame(self, shared: SharedFrameEvaluation) -> None: ...


class ProcessingDiagnostics(Protocol):
    def frame_processing_started(
        self,
        frame: Frame,
        processing_started_at: MonotonicTime,
    ) -> None: ...

    def frame_normalization_failed(
        self,
        error: FrameNormalizationError,
    ) -> None: ...

    def frame_processing_completed(self, context: FrameContext) -> None: ...


class ProcessingRuntime:
    """Normalize captured frames and publish the shared evaluation to instances."""

    def __init__(
        self,
        instances: tuple[FrameSink, ...],
        frame_buffer: LatestFrameBuffer,
        normalizer: FrameNormalizer,
        *,
        diagnostics: ProcessingDiagnostics,
        time_provider: TimeProvider | None = None,
    ) -> None:
        self._instances = instances
        self._frame_buffer = frame_buffer
        self._normalizer = normalizer
        self._diagnostics = diagnostics
        self._time_provider = time_provider or TimeProvider()
        self._stop_requested = threading.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._frame_buffer.stop()

    def run(self) -> None:
        while not self._stop_requested.is_set():
            frame = self._frame_buffer.take(DEFAULT_FRAME_WAIT_SECONDS)
            if self._stop_requested.is_set():
                return
            if frame is None:
                continue
            now = self._time_provider.now()
            self._diagnostics.frame_processing_started(frame, now)
            normalized = self._normalizer.normalize(frame)
            if isinstance(normalized, FrameNormalizationError):
                self._diagnostics.frame_normalization_failed(normalized)
                self.request_stop()
                return
            shared = SharedFrameEvaluation(frame=normalized, now=now)
            for instance in self._instances:
                instance.publish_frame(shared)
            self._diagnostics.frame_processing_completed(FrameContext(shared=shared))
