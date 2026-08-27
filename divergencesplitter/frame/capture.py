import logging
import math
import threading
import time

from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSource,
    FrameSourceState,
)

DEFAULT_RETRY_DELAY_SECONDS = 0.1


class LatestFrameBuffer:
    """Thread-safe single-slot buffer that delivers each publish at most once."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._condition = threading.Condition()
        self._logger = logger or logging.getLogger(__name__)
        self._frame: Frame | None = None
        self._generation = 0
        self._consumed_generation = 0
        self._stopped = False
        self._received_count = 0
        self._overwritten_count = 0
        self._processed_count = 0

    @property
    def received_count(self) -> int:
        with self._condition:
            return self._received_count

    @property
    def overwritten_count(self) -> int:
        with self._condition:
            return self._overwritten_count

    @property
    def processed_count(self) -> int:
        with self._condition:
            return self._processed_count

    @property
    def pending_count(self) -> int:
        with self._condition:
            return int(self._generation > self._consumed_generation)

    @property
    def is_stopped(self) -> bool:
        with self._condition:
            return self._stopped

    def publish(self, frame: Frame) -> bool:
        """Publish a frame, replacing an older unprocessed frame if necessary."""
        with self._condition:
            if self._stopped:
                return False
            if self._generation > self._consumed_generation:
                self._overwritten_count += 1
            self._generation += 1
            self._frame = frame
            self._received_count += 1
            received_count = self._received_count
            overwritten_count = self._overwritten_count
            self._condition.notify_all()
        self._log(
            logging.DEBUG,
            "frame_buffer.published",
            received_count=received_count,
            overwritten_count=overwritten_count,
        )
        return True

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
            self._processed_count += 1
            processed_count = self._processed_count
        self._log(
            logging.DEBUG,
            "frame_buffer.processed",
            processed_count=processed_count,
        )
        return frame

    def stop(self) -> None:
        """Reject future publishes and release all waiting consumers."""
        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            self._condition.notify_all()
        self._log(logging.INFO, "frame_buffer.stopped")

    def _log(self, level: int, event: str, **extra: object) -> None:
        try:
            self._logger.log(
                level,
                event,
                extra={"event_name": event, **extra},
            )
        except Exception:  # noqa: BLE001
            return


class CaptureStateMachine[ErrorT]:
    """Own a FrameSource and publish its frames until stopped."""

    def __init__(
        self,
        source: FrameSource[ErrorT],
        buffer: LatestFrameBuffer,
        *,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        logger: logging.Logger | None = None,
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
        self._logger = logger or logging.getLogger(__name__)
        self._stop_requested = threading.Event()
        self._last_source_state: FrameSourceState | None = None
        self._received_count = 0
        self._retry_count = 0

    @property
    def received_count(self) -> int:
        return self._received_count

    @property
    def retry_count(self) -> int:
        return self._retry_count

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
                self._log(
                    logging.WARNING,
                    "capture.source_state_unavailable",
                    exception_type=type(error).__name__,
                    exception_message=str(error),
                )
            self._log(logging.INFO, "capture.source_closed")
            self._log(logging.INFO, "capture.stopped")

    def _prepare(self) -> None:
        self._log(logging.DEBUG, "capture.preparing")
        error = self._source.prepare()
        self._observe_source_state()
        if self._stop_requested.is_set():
            return
        if error is not None:
            self._handle_error(error)
            return
        self._log(logging.DEBUG, "capture.prepared")
        if self._source.state is FrameSourceState.NOT_READY:
            self._wait_before_retry()

    def _capture(self) -> None:
        result = self._source.read()
        self._observe_source_state()
        if isinstance(result, Frame):
            self._received_count += 1
            accepted = self._buffer.publish(result)
            self._log(
                logging.DEBUG,
                "capture.frame_received",
                received_count=self._received_count,
                accepted=accepted,
                overwritten_count=self._buffer.overwritten_count,
                processed_count=self._buffer.processed_count,
            )
            return
        if self._stop_requested.is_set():
            return
        self._handle_error(result)

    def _handle_error(self, error: ErrorT) -> None:
        self._log(
            logging.WARNING,
            "capture.source_error",
            exception_type=type(error).__name__,
            exception_message=str(error),
        )
        action = self._source.handle_error(error)
        state = self._observe_source_state()
        self._log(
            logging.INFO,
            "capture.error_handled",
            error_action=action.name,
            source_state=state.name,
        )
        if action is ErrorAction.STOP:
            self._stop_requested.set()
            return
        if action is not ErrorAction.RETRY:
            raise ValueError(f"invalid error action: {action!r}")
        self._retry_count += 1
        if state is FrameSourceState.NOT_READY:
            self._wait_before_retry()

    def _wait_before_retry(self) -> None:
        self._stop_requested.wait(self._retry_delay_seconds)

    def _observe_source_state(self) -> FrameSourceState:
        state = self._source.state
        if state is not self._last_source_state:
            previous = self._last_source_state
            self._last_source_state = state
            self._log(
                logging.INFO,
                "capture.source_state_changed",
                previous_source_state=None if previous is None else previous.name,
                source_state=state.name,
            )
        return state

    def _log(self, level: int, event: str, **extra: object) -> None:
        try:
            self._logger.log(
                level,
                event,
                extra={"event_name": event, **extra},
            )
        except Exception:  # noqa: BLE001
            return
