import math
import threading
import time
from collections.abc import Mapping
from enum import Enum, auto
from typing import Protocol

from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSource,
    FrameSourceState,
)

DEFAULT_RETRY_DELAY_SECONDS = 0.1


class CaptureDiagnostics(Protocol):
    def record(self, event: str, fields: Mapping[str, object]) -> None: ...


class PublishResult(Enum):
    PUBLISHED = auto()
    OVERWROTE = auto()
    STOPPED = auto()


class LatestFrameBuffer:
    """Thread-safe single-slot buffer that delivers each publish at most once."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: Frame | None = None
        self._generation = 0
        self._consumed_generation = 0
        self._stopped = False

    def publish(self, frame: Frame) -> PublishResult:
        """Publish a frame, replacing an older unprocessed frame if necessary."""
        with self._condition:
            if self._stopped:
                return PublishResult.STOPPED
            result = (
                PublishResult.OVERWROTE
                if self._generation > self._consumed_generation
                else PublishResult.PUBLISHED
            )
            self._generation += 1
            self._frame = frame
            self._condition.notify_all()
            return result

    def take(self, timeout: float | None = None) -> Frame | None:
        """Wait for and consume the newest frame, or return ``None`` on stop/timeout."""
        if timeout is not None and (
            isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0
        ):
            raise ValueError("timeout must be non-negative or None")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._generation <= self._consumed_generation:
                if self._stopped:
                    return None
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            frame = self._frame
            assert frame is not None
            self._consumed_generation = self._generation
            self._frame = None
            return frame

    def stop(self) -> None:
        """Reject future publishes and release all waiting consumers."""
        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            self._condition.notify_all()


class CaptureStateMachine[ErrorT]:
    """Own a FrameSource and publish its frames until stopped."""

    def __init__(
        self,
        source: FrameSource[ErrorT],
        buffer: LatestFrameBuffer,
        *,
        diagnostics: CaptureDiagnostics,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ) -> None:
        if (
            isinstance(retry_delay_seconds, bool)
            or not math.isfinite(retry_delay_seconds)
            or retry_delay_seconds <= 0
        ):
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
                self._diagnose(
                    "capture.source_state_unavailable",
                    exception_type=type(error).__name__,
                    exception_message=str(error),
                )
            self._diagnose("capture.source_closed")
            self._diagnose("capture.stopped")

    def _prepare(self) -> None:
        self._diagnose("capture.preparing")
        error = self._source.prepare()
        self._observe_source_state()
        if self._stop_requested.is_set():
            return
        if error is not None:
            self._handle_error(error)
            return
        self._diagnose("capture.prepared")
        if self._source.state is FrameSourceState.NOT_READY:
            self._wait_before_retry()

    def _capture(self) -> None:
        result = self._source.read()
        self._observe_source_state()
        if isinstance(result, Frame):
            publish_result = self._buffer.publish(result)
            self._diagnose(
                "capture.frame_received",
                publish_result=publish_result.name,
            )
            return
        if self._stop_requested.is_set():
            return
        self._handle_error(result)

    def _handle_error(self, error: ErrorT) -> None:
        self._diagnose(
            "capture.source_error",
            exception_type=type(error).__name__,
            exception_message=str(error),
        )
        action = self._source.handle_error(error)
        state = self._observe_source_state()
        self._diagnose(
            "capture.error_handled",
            error_action=action.name,
            source_state=state.name,
        )
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
            self._diagnose(
                "capture.source_state_changed",
                previous_source_state=None if previous is None else previous.name,
                source_state=state.name,
            )
        return state

    def _diagnose(self, event: str, **fields: object) -> None:
        try:
            self._diagnostics.record(event, fields)
        except Exception:  # noqa: BLE001
            return
