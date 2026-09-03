import math
import threading
from enum import Enum, auto
from typing import Protocol

from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSource,
    FrameSourceError,
    FrameSourceState,
)

DEFAULT_RETRY_DELAY_SECONDS = 0.1


class PublishResult(Enum):
    PUBLISHED = auto()
    OVERWROTE = auto()
    STOPPED = auto()


class CaptureDiagnostics(Protocol):
    """Receives capture facts without raising exceptions to the caller."""

    def preparing(self) -> None: ...

    def prepared(self) -> None: ...

    def frame_received(self, frame: Frame, publish_result: PublishResult) -> None: ...

    def source_error(self, error: FrameSourceError) -> None: ...

    def error_handled(
        self,
        action: ErrorAction,
        state: FrameSourceState,
    ) -> None: ...

    def source_state_changed(
        self,
        previous: FrameSourceState | None,
        current: FrameSourceState,
    ) -> None: ...

    def source_state_unavailable(self, error: Exception) -> None: ...

    def source_closed(self) -> None: ...

    def stopped(self) -> None: ...


class LatestFrameBuffer:
    """Thread-safe single-slot buffer that delivers each publish at most once."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: Frame | None = None
        self._stopped = False

    def publish(self, frame: Frame) -> PublishResult:
        """Publish a frame, replacing an older unprocessed frame if necessary."""
        with self._condition:
            if self._stopped:
                return PublishResult.STOPPED
            result = (
                PublishResult.OVERWROTE
                if self._frame is not None
                else PublishResult.PUBLISHED
            )
            self._frame = frame
            self._condition.notify_all()
            return result

    def take(self) -> Frame | None:
        """Wait for and consume the newest frame, or return ``None`` on stop."""
        with self._condition:
            while self._frame is None:
                if self._stopped:
                    return None
                self._condition.wait()
            frame = self._frame
            self._frame = None
            return frame

    def stop(self) -> None:
        """Reject future publishes and release all waiting consumers."""
        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            self._condition.notify_all()


class CaptureStateMachine:
    """Own a FrameSource and publish its frames until stopped."""

    def __init__(
        self,
        source: FrameSource,
        buffer: LatestFrameBuffer,
        *,
        diagnostics: CaptureDiagnostics,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ) -> None:
        if not math.isfinite(retry_delay_seconds) or retry_delay_seconds <= 0:
            raise ValueError("retry_delay_seconds must be positive")
        self._source = source
        self._buffer = buffer
        self._retry_delay_seconds = retry_delay_seconds
        self._diagnostics = diagnostics
        self._stop_requested = threading.Event()
        self._last_source_state: FrameSourceState | None = None

    @property
    def is_stopped(self) -> bool:
        return self._stop_requested.is_set()

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._buffer.stop()

    def run(self) -> None:
        try:
            with self._source:
                while not self._stop_requested.is_set():
                    state = self._observe_source_state()
                    if state is FrameSourceState.NOT_READY:
                        self._prepare()
                    else:
                        self._capture()
        finally:
            self._stop_requested.set()
            self._buffer.stop()
            try:
                self._observe_source_state()
            except Exception as error:  # noqa: BLE001
                self._diagnostics.source_state_unavailable(error)
            self._diagnostics.source_closed()
            self._diagnostics.stopped()

    def _prepare(self) -> None:
        self._diagnostics.preparing()
        error = self._source.prepare()
        self._observe_source_state()
        if self._stop_requested.is_set():
            return
        if error is not None:
            self._handle_error(error)
            return
        self._diagnostics.prepared()
        if self._source.state is FrameSourceState.NOT_READY:
            self._wait_before_retry()

    def _capture(self) -> None:
        result = self._source.read()
        if isinstance(result, Frame):
            self._observe_source_state()
            publish_result = self._buffer.publish(result)
            self._diagnostics.frame_received(result, publish_result)
            if publish_result is PublishResult.STOPPED:
                self._stop_requested.set()
            return
        self._observe_source_state()
        if self._stop_requested.is_set():
            return
        self._handle_error(result)

    def _handle_error(self, error: FrameSourceError) -> None:
        self._diagnostics.source_error(error)
        action = self._source.handle_error(error)
        state = self._observe_source_state()
        self._diagnostics.error_handled(action, state)
        if action is ErrorAction.STOP:
            self._stop_requested.set()
            return
        if action is not ErrorAction.RETRY:
            raise ValueError(f"invalid error action: {action!r}")
        if state is FrameSourceState.NOT_READY:
            self._wait_before_retry()

    def _wait_before_retry(self) -> None:
        self._stop_requested.wait(self._retry_delay_seconds)

    def _observe_source_state(self) -> FrameSourceState:
        state = self._source.state
        if state is not self._last_source_state:
            previous = self._last_source_state
            self._last_source_state = state
            self._diagnostics.source_state_changed(previous, state)
        return state
