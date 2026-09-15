"""Single-thread owner for one integrated LiveSplit Bridge connection.

The worker owns the RPC client and all protocol state (baseline, session and
sequence validation, resynchronization, and action execution). Raw SUB events
arrive through a :class:`BridgeEventReceiver` running on its own thread, so the
worker never blocks on a SUB receive.
"""

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import (
    BridgeClientError,
    BridgeConnectionLostError,
    BridgeEventSubscriber,
    BridgeProtocolError,
    BridgeRemoteError,
    common_pb2,
)

from divergencesplitter_runtime.livesplit.adapter import (
    LiveSplitBridgeAdapter,
    LiveSplitBridgeDiagnostics,
)
from divergencesplitter_runtime.livesplit.event_receiver import (
    DEFAULT_EVENT_CAPACITY,
    DEFAULT_EVENT_RECEIVE_TIMEOUT_MS,
    BridgeEventConnectionLost,
    BridgeEventReceived,
    BridgeEventReceiver,
    BridgeEventSubscriberLike,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
)

DEFAULT_RECONNECT_DELAY_SECONDS = 0.1
DEFAULT_UPDATE_CAPACITY = 16


@dataclass(frozen=True)
class BridgeActionRequest:
    action: Action
    expected_snapshot: LiveSplitSnapshot


class ActionSubmission(Enum):
    ACCEPTED = auto()
    RESET_REPLACED = auto()
    REJECTED = auto()
    STOPPED = auto()


class BridgeWorkerState(Enum):
    CONNECTING = auto()
    READY = auto()
    FAILED = auto()
    STOPPED = auto()


class BridgeWorkerDiagnostics(LiveSplitBridgeDiagnostics, Protocol):
    def worker_started(self, connection: LiveSplitConnection) -> None: ...

    def initial_sync_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None: ...

    def connection_lost(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None: ...

    def reconnect_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None: ...

    def update_queue_overflowed(self, connection: LiveSplitConnection) -> None: ...

    def action_submitted(
        self,
        connection: LiveSplitConnection,
        request: BridgeActionRequest,
        result: ActionSubmission,
    ) -> None: ...

    def worker_stopped(self, connection: LiveSplitConnection) -> None: ...


class _ActionSlot:
    def __init__(self, wakeup: threading.Event | None = None) -> None:
        self._lock = threading.Lock()
        self._wakeup = wakeup
        self._request: BridgeActionRequest | None = None
        self._stopped = False

    def submit(self, request: BridgeActionRequest) -> ActionSubmission:
        with self._lock:
            if self._stopped:
                return ActionSubmission.STOPPED
            current = self._request
            if current is None:
                self._request = request
                result = ActionSubmission.ACCEPTED
            elif (
                request.action.operation == "reset"
                and current.action.operation != "reset"
            ):
                self._request = request
                result = ActionSubmission.RESET_REPLACED
            else:
                result = ActionSubmission.REJECTED
        if result is not ActionSubmission.REJECTED and self._wakeup is not None:
            self._wakeup.set()
        return result

    def take(self) -> BridgeActionRequest | None:
        with self._lock:
            request = self._request
            self._request = None
            return request

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            self._request = None

    def clear(self) -> None:
        with self._lock:
            self._request = None


class _UpdateQueue:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("update capacity must be positive")
        self._capacity = capacity
        self._lock = threading.Lock()
        self._updates: deque[LiveSplitUpdate] = deque()

    def put(self, update: LiveSplitUpdate) -> bool:
        with self._lock:
            if len(self._updates) >= self._capacity:
                return False
            self._updates.append(update)
            return True

    def replace(self, update: LiveSplitUpdate) -> None:
        with self._lock:
            self._updates.clear()
            self._updates.append(update)

    def drain(self) -> tuple[LiveSplitUpdate, ...]:
        with self._lock:
            updates = tuple(self._updates)
            self._updates.clear()
            return updates


class BridgeWorker:
    """Own and serialize all Bridge operations for one connection."""

    def __init__(
        self,
        connection: LiveSplitConnection,
        *,
        diagnostics: BridgeWorkerDiagnostics,
        receive_timeout_ms: int = DEFAULT_EVENT_RECEIVE_TIMEOUT_MS,
        reconnect_delay_seconds: float = DEFAULT_RECONNECT_DELAY_SECONDS,
        update_capacity: int = DEFAULT_UPDATE_CAPACITY,
        event_capacity: int = DEFAULT_EVENT_CAPACITY,
        rpc_timeout_ms: int = 3000,
        heartbeat_timeout_ms: int = 3000,
        subscriber_factory: Callable[[], BridgeEventSubscriberLike] | None = None,
    ) -> None:
        if receive_timeout_ms < 0:
            raise ValueError("receive_timeout_ms must be non-negative")
        if reconnect_delay_seconds < 0:
            raise ValueError("reconnect_delay_seconds must be non-negative")
        if event_capacity <= 0:
            raise ValueError("event capacity must be positive")
        self._connection = connection
        self._diagnostics = diagnostics
        self._receive_timeout_ms = receive_timeout_ms
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._rpc_timeout_ms = rpc_timeout_ms
        self._heartbeat_timeout_ms = heartbeat_timeout_ms
        self._event_capacity = event_capacity
        self._subscriber_factory = (
            subscriber_factory
            if subscriber_factory is not None
            else self._create_subscriber
        )
        self._wakeup = threading.Event()
        self._actions = _ActionSlot(self._wakeup)
        self._updates = _UpdateQueue(update_capacity)
        self._stop_requested = threading.Event()
        self._initialized = threading.Event()
        self._available = threading.Event()
        self._terminated = threading.Event()
        self._initial_error: Exception | None = None
        self._state = BridgeWorkerState.CONNECTING
        self._state_lock = threading.RLock()
        self._generation = 0
        self._sync_in_progress = False

    @property
    def state(self) -> BridgeWorkerState:
        with self._state_lock:
            return self._state

    @property
    def failure(self) -> Exception | None:
        with self._state_lock:
            return self._initial_error

    @property
    def is_available(self) -> bool:
        return self.state is BridgeWorkerState.READY and self._available.is_set()

    def submit_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
        *,
        generation: int | None = None,
    ) -> ActionSubmission:
        request = BridgeActionRequest(action, expected_snapshot)
        with self._state_lock:
            if self._stop_requested.is_set():
                result = ActionSubmission.STOPPED
            elif not self.is_available or (
                generation is not None and generation != self._generation
            ):
                result = ActionSubmission.REJECTED
            else:
                result = self._actions.submit(request)
        self._diagnostics.action_submitted(self._connection, request, result)
        return result

    @property
    def connection_state(self) -> tuple[BridgeWorkerState, int]:
        with self._state_lock:
            return self._state, self._generation

    def drain_connection_updates(
        self,
    ) -> tuple[BridgeWorkerState, int, tuple[LiveSplitUpdate, ...]]:
        """Read updates and their connection generation atomically."""
        with self._state_lock:
            updates = self._updates.drain()
            if (
                not self._sync_in_progress
                and not self._terminated.is_set()
                and not self._stop_requested.is_set()
                and any(
                    update.kind
                    in (LiveSplitUpdateKind.INITIAL, LiveSplitUpdateKind.RESYNC)
                    for update in updates
                )
            ):
                self._available.set()
                self._state = BridgeWorkerState.READY
            return self._state, self._generation, updates

    def drain_updates(self) -> tuple[LiveSplitUpdate, ...]:
        return self.drain_connection_updates()[2]

    def wait_until_initialized(self, timeout_seconds: float | None = None) -> None:
        if not self._initialized.wait(timeout_seconds):
            raise TimeoutError("Bridge worker did not complete initial synchronization")
        if self._initial_error is not None:
            raise self._initial_error

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._actions.stop()
        self._wakeup.set()
        self._initialized.set()

    def run(self) -> None:
        adapter: LiveSplitBridgeAdapter | None = None
        receiver: BridgeEventReceiver | None = None
        try:
            self._diagnostics.worker_started(self._connection)
            while not self._stop_requested.is_set():
                try:
                    receiver = self._create_receiver()
                    receiver.start()
                    receiver.wait_until_started()
                    if self._stop_requested.is_set():
                        return
                    adapter = LiveSplitBridgeAdapter(
                        self._connection,
                        diagnostics=self._diagnostics,
                        rpc_timeout_ms=self._rpc_timeout_ms,
                    )
                    # Attach establishes the baseline after SUB reception has
                    # already started, so queued events can be validated against
                    # it without an avoidable gap.
                    initial = adapter.attach()
                    with self._state_lock:
                        if self._stop_requested.is_set():
                            return
                        self._updates.replace(initial)
                    self._initialized.set()
                    self._run_loop(adapter, receiver)
                    return
                except (BridgeProtocolError, BridgeRemoteError, ValueError) as error:
                    self._fail(error)
                    return
                except (BridgeClientError, BridgeConnectionLostError) as error:
                    if not self._initialized.is_set():
                        self._diagnostics.initial_sync_failed(self._connection, error)
                    else:
                        self._connection_lost(error)
                except Exception as error:  # noqa: BLE001
                    self._fail(error)
                    return
                finally:
                    if receiver is not None:
                        receiver.stop()
                        receiver = None
                    if adapter is not None:
                        adapter.close()
                        adapter = None
                self._stop_requested.wait(self._reconnect_delay_seconds)
        finally:
            with self._state_lock:
                self._terminated.set()
                self._available.clear()
                if self._stop_requested.is_set():
                    self._state = BridgeWorkerState.STOPPED
                self._actions.stop()
            self._initialized.set()
            self._diagnostics.worker_stopped(self._connection)

    def _create_subscriber(self) -> BridgeEventSubscriber:
        return BridgeEventSubscriber(
            self._connection.event_endpoint,
            heartbeat_timeout_ms=self._heartbeat_timeout_ms,
        )

    def _create_receiver(self) -> BridgeEventReceiver:
        return BridgeEventReceiver(
            subscriber_factory=self._subscriber_factory,
            wakeup=self._wakeup,
            receive_timeout_ms=self._receive_timeout_ms,
            capacity=self._event_capacity,
        )

    def _fail(self, error: Exception) -> None:
        self._initial_error = error
        with self._state_lock:
            self._state = BridgeWorkerState.FAILED
            self._available.clear()
            self._actions.clear()
            self._updates.drain()
        self._diagnostics.initial_sync_failed(self._connection, error)
        self._initialized.set()

    def _connection_lost(self, error: Exception) -> None:
        with self._state_lock:
            self._state = BridgeWorkerState.CONNECTING
            self._generation += 1
            self._sync_in_progress = False
            self._available.clear()
            self._actions.clear()
            self._updates.drain()
        self._diagnostics.connection_lost(self._connection, error)

    def _begin_resync(self) -> None:
        with self._state_lock:
            self._available.clear()
            self._actions.clear()
            self._sync_in_progress = True

    def _run_loop(
        self,
        adapter: LiveSplitBridgeAdapter,
        receiver: BridgeEventReceiver,
    ) -> None:
        while not self._stop_requested.is_set():
            self._wakeup.clear()
            self._process_pending(adapter, receiver)
            if self._stop_requested.is_set():
                return
            self._wakeup.wait()

    def _process_pending(
        self,
        adapter: LiveSplitBridgeAdapter,
        receiver: BridgeEventReceiver,
    ) -> None:
        messages = receiver.drain()
        overflowed = receiver.take_overflow()
        for message in messages:
            if isinstance(message, BridgeEventConnectionLost):
                raise message.error
        if overflowed:
            # Dropped events make the stream non-contiguous: resynchronize
            # instead of pretending the remaining events are authoritative.
            self._begin_resync()
            update = adapter.resync(LiveSplitResyncReason.EVENT_INBOX_OVERFLOW)
            self._publish(update, adapter)
            return
        # Apply every already-received authoritative event before validating a
        # pending action, so an action planned against an older revision is
        # rejected rather than sent.
        for message in messages:
            if isinstance(message, BridgeEventReceived):
                self._apply_event(adapter, message.event)
        if not self.is_available:
            return
        request = self._actions.take()
        if request is not None:
            adapter.execute_action(request.action, request.expected_snapshot)

    def _apply_event(
        self,
        adapter: LiveSplitBridgeAdapter,
        event: common_pb2.BridgeEvent,
    ) -> None:
        received = adapter.handle_event(event)
        if received is LiveSplitResyncReason.SESSION_CHANGED:
            raise BridgeConnectionLostError("Bridge session changed")
        if isinstance(received, LiveSplitResyncReason):
            self._begin_resync()
            update = adapter.resync(received)
        else:
            update = received
        if update is not None:
            self._publish(update, adapter)

    def _publish(
        self,
        update: LiveSplitUpdate,
        adapter: LiveSplitBridgeAdapter,
    ) -> None:
        with self._state_lock:
            self._sync_in_progress = False
            if update.kind is LiveSplitUpdateKind.RESYNC:
                self._available.clear()
                self._actions.clear()
            if self._updates.put(update):
                return
            self._available.clear()
            self._actions.clear()
            self._sync_in_progress = True
        self._diagnostics.update_queue_overflowed(self._connection)
        resync = adapter.resync(LiveSplitResyncReason.UPDATE_QUEUE_OVERFLOW)
        with self._state_lock:
            # An overflow before Processing drains INITIAL must retain the
            # session-start marker, using the latest authoritative snapshot.
            pending = self._updates.drain()
            if any(item.kind is LiveSplitUpdateKind.INITIAL for item in pending):
                resync = LiveSplitUpdate(
                    LiveSplitUpdateKind.INITIAL,
                    resync.snapshot,
                    resync.run_info,
                )
            self._updates.replace(resync)
            self._sync_in_progress = False
