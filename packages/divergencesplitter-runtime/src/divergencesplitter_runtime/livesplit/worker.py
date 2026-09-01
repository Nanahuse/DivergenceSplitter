"""Single-thread owner for one integrated LiveSplit Bridge client."""

import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import BridgeClientError, BridgeConnectionLostError

from divergencesplitter_runtime.livesplit.adapter import (
    LiveSplitBridgeAdapter,
    LiveSplitBridgeDiagnostics,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
)

DEFAULT_RECEIVE_TIMEOUT_MS = 50
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
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request: BridgeActionRequest | None = None
        self._stopped = False

    def submit(self, request: BridgeActionRequest) -> ActionSubmission:
        with self._lock:
            if self._stopped:
                return ActionSubmission.STOPPED
            current = self._request
            if current is None:
                self._request = request
                return ActionSubmission.ACCEPTED
            if (
                request.action.operation == "reset"
                and current.action.operation != "reset"
            ):
                self._request = request
                return ActionSubmission.RESET_REPLACED
            return ActionSubmission.REJECTED

    def take(self) -> BridgeActionRequest | None:
        with self._lock:
            request = self._request
            self._request = None
            return request

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
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
        receive_timeout_ms: int = DEFAULT_RECEIVE_TIMEOUT_MS,
        reconnect_delay_seconds: float = DEFAULT_RECONNECT_DELAY_SECONDS,
        update_capacity: int = DEFAULT_UPDATE_CAPACITY,
        rpc_timeout_ms: int = 3000,
        heartbeat_timeout_ms: int = 3000,
    ) -> None:
        if receive_timeout_ms < 0:
            raise ValueError("receive_timeout_ms must be non-negative")
        if reconnect_delay_seconds < 0:
            raise ValueError("reconnect_delay_seconds must be non-negative")
        self._connection = connection
        self._diagnostics = diagnostics
        self._receive_timeout_ms = receive_timeout_ms
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._rpc_timeout_ms = rpc_timeout_ms
        self._heartbeat_timeout_ms = heartbeat_timeout_ms
        self._actions = _ActionSlot()
        self._updates = _UpdateQueue(update_capacity)
        self._stop_requested = threading.Event()
        self._initialized = threading.Event()
        self._available = threading.Event()
        self._terminated = threading.Event()
        self._initial_error: Exception | None = None

    @property
    def is_available(self) -> bool:
        return self._available.is_set() and not self._terminated.is_set()

    def submit_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
    ) -> ActionSubmission:
        request = BridgeActionRequest(action, expected_snapshot)
        result = self._actions.submit(request)
        self._diagnostics.action_submitted(self._connection, request, result)
        return result

    def drain_updates(self) -> tuple[LiveSplitUpdate, ...]:
        updates = self._updates.drain()
        if not self._terminated.is_set() and any(
            update.kind
            in (
                LiveSplitUpdateKind.INITIAL,
                LiveSplitUpdateKind.RESYNC,
            )
            for update in updates
        ):
            self._available.set()
        return updates

    def wait_until_initialized(self, timeout_seconds: float | None = None) -> None:
        if not self._initialized.wait(timeout_seconds):
            raise TimeoutError("Bridge worker did not complete initial synchronization")
        if self._initial_error is not None:
            raise self._initial_error

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._actions.stop()

    def run(self) -> None:
        adapter: LiveSplitBridgeAdapter | None = None
        try:
            adapter = LiveSplitBridgeAdapter(
                self._connection,
                diagnostics=self._diagnostics,
                rpc_timeout_ms=self._rpc_timeout_ms,
                heartbeat_timeout_ms=self._heartbeat_timeout_ms,
            )
            initial = adapter.attach()
            self._updates.put(initial)
            self._initialized.set()
            self._diagnostics.worker_started(self._connection)
            self._run_loop(adapter)
        except Exception as error:  # noqa: BLE001
            if not self._initialized.is_set():
                self._initial_error = error
                self._initialized.set()
                self._diagnostics.initial_sync_failed(self._connection, error)
            else:
                self._diagnostics.connection_lost(self._connection, error)
        finally:
            self._terminated.set()
            self._available.clear()
            self._actions.stop()
            if adapter is not None:
                adapter.close()
            self._diagnostics.worker_stopped(self._connection)

    def _run_loop(self, adapter: LiveSplitBridgeAdapter) -> None:
        while not self._stop_requested.is_set():
            try:
                received = adapter.receive(timeout_ms=self._receive_timeout_ms)
                if isinstance(received, LiveSplitResyncReason):
                    self._available.clear()
                    update = adapter.resync(received)
                else:
                    update = received
            except BridgeConnectionLostError as error:
                self._diagnostics.connection_lost(self._connection, error)
                self._reconnect(adapter)
                continue
            except (BridgeClientError, ValueError) as error:
                self._diagnostics.connection_lost(self._connection, error)
                self._reconnect(adapter)
                continue

            if update is not None:
                self._publish(update, adapter)
            if not self.is_available:
                continue
            request = self._actions.take()
            if request is not None:
                adapter.execute_action(request.action, request.expected_snapshot)

    def _publish(
        self,
        update: LiveSplitUpdate,
        adapter: LiveSplitBridgeAdapter,
    ) -> None:
        if update.kind is LiveSplitUpdateKind.RESYNC:
            self._available.clear()
        if self._updates.put(update):
            return
        self._available.clear()
        self._diagnostics.update_queue_overflowed(self._connection)
        try:
            resync = adapter.resync(LiveSplitResyncReason.UPDATE_QUEUE_OVERFLOW)
        except Exception as error:  # noqa: BLE001
            self._diagnostics.connection_lost(self._connection, error)
            self._reconnect(adapter)
            return
        self._updates.replace(resync)

    def _reconnect(self, adapter: LiveSplitBridgeAdapter) -> None:
        self._available.clear()
        while not self._stop_requested.is_set():
            try:
                update = adapter.reconnect()
            except Exception as error:  # noqa: BLE001
                self._diagnostics.reconnect_failed(self._connection, error)
                self._stop_requested.wait(self._reconnect_delay_seconds)
                continue
            self._updates.replace(update)
            return
