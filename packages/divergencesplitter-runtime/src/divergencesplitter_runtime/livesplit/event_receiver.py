"""Dedicated SUB event receive thread for one LiveSplit Bridge connection.

The receiver owns the :class:`BridgeEventSubscriber` socket and drains it on
its own thread. It performs no protocol or state interpretation: raw events and
connection-loss notifications are forwarded, in order, to the worker through a
bounded inbox. Baseline, session, sequence validation, resynchronization, and
action execution stay on the worker thread.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from livesplit_bridge import BridgeConnectionLostError, common_pb2

DEFAULT_EVENT_RECEIVE_TIMEOUT_MS = 50
DEFAULT_EVENT_CAPACITY = 256


class BridgeEventSubscriberLike(Protocol):
    """Transport contract implemented by ``BridgeEventSubscriber``."""

    def receive(
        self, *, timeout_ms: int | None = None
    ) -> common_pb2.BridgeEvent | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class BridgeEventReceived:
    event: common_pb2.BridgeEvent


@dataclass(frozen=True)
class BridgeEventConnectionLost:
    error: Exception


BridgeEventMessage = BridgeEventReceived | BridgeEventConnectionLost


class BridgeEventReceiver:
    """Own one SUB socket and forward Bridge events in receive order."""

    def __init__(
        self,
        *,
        subscriber_factory: Callable[[], BridgeEventSubscriberLike],
        wakeup: threading.Event,
        receive_timeout_ms: int = DEFAULT_EVENT_RECEIVE_TIMEOUT_MS,
        capacity: int = DEFAULT_EVENT_CAPACITY,
    ) -> None:
        if receive_timeout_ms < 0:
            raise ValueError("receive_timeout_ms must be non-negative")
        if capacity <= 0:
            raise ValueError("event capacity must be positive")
        self._subscriber_factory = subscriber_factory
        self._wakeup = wakeup
        self._receive_timeout_ms = receive_timeout_ms
        self._capacity = capacity
        self._lock = threading.Lock()
        self._messages: deque[BridgeEventMessage] = deque()
        self._overflowed = False
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._start_error: Exception | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the receive thread; return before the subscriber is ready."""
        self._thread = threading.Thread(
            target=self._run,
            name="bridge-event-receiver",
            daemon=True,
        )
        self._thread.start()

    def wait_until_started(self) -> None:
        """Block until the subscriber exists, re-raising a creation failure."""
        self._started.wait()
        if self._start_error is not None:
            raise self._start_error

    def drain(self) -> tuple[BridgeEventMessage, ...]:
        """Return queued messages in receive order and clear the inbox."""
        with self._lock:
            messages = tuple(self._messages)
            self._messages.clear()
            return messages

    def take_overflow(self) -> bool:
        """Consume and report whether the inbox dropped a message."""
        with self._lock:
            overflowed = self._overflowed
            self._overflowed = False
            return overflowed

    def stop(self) -> None:
        """Stop receiving and join the receive thread."""
        self._stopped.set()
        thread = self._thread
        if thread is not None:
            thread.join()

    def _run(self) -> None:
        subscriber: BridgeEventSubscriberLike | None = None
        try:
            subscriber = self._subscriber_factory()
        except Exception as error:  # noqa: BLE001
            self._start_error = error
            self._started.set()
            return
        self._started.set()
        try:
            while not self._stopped.is_set():
                try:
                    event = subscriber.receive(timeout_ms=self._receive_timeout_ms)
                except BridgeConnectionLostError as error:
                    self._publish(BridgeEventConnectionLost(error))
                    return
                except Exception as error:  # noqa: BLE001
                    self._publish(BridgeEventConnectionLost(error))
                    return
                if event is not None:
                    self._publish(BridgeEventReceived(event))
        finally:
            subscriber.close()

    def _publish(self, message: BridgeEventMessage) -> None:
        with self._lock:
            if len(self._messages) >= self._capacity:
                # Signal integrity loss without silently pretending the stream
                # is contiguous. The worker resynchronizes on the next drain.
                self._overflowed = True
            else:
                self._messages.append(message)
        self._wakeup.set()
