"""Dedicated execution thread owner for one scenario instance.

One :class:`InstanceRuntime` owns everything that belongs to a single
``ScenarioInstance``: the RPC adapter, protocol baseline, scenario runtime,
frame evaluation, and action dispatch. All of it runs on the instance's own
thread, so the ``ScenarioRuntime`` is never touched from another thread.

Only raw SUB reception stays on the shared :class:`BridgeEventReceiver` thread.
The receiver forwards ordered Bridge events (and connection loss) to the
instance thread through a bounded inbox and a wake event.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from divergencesplitter import Action, LiveSplitConnection, MonotonicTime
from divergencesplitter.clock import TimeProvider
from divergencesplitter.frame.models import FrameContext, SharedFrameEvaluation
from divergencesplitter.scenario.models import Scenario
from livesplit_bridge import (
    BridgeClientError,
    BridgeConnectionLostError,
    BridgeEventSubscriber,
    BridgeProtocolError,
    BridgeRemoteError,
    common_pb2,
)

from divergencesplitter_runtime.configuration.validation import validate_split_count
from divergencesplitter_runtime.livesplit.adapter import (
    ActionExecution,
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
    LiveSplitRunInfo,
    LiveSplitUpdate,
)
from divergencesplitter_runtime.scenario import ScenarioRuntime

DEFAULT_RECONNECT_DELAY_SECONDS = 0.1


class InstanceRuntimeState(Enum):
    CONNECTING = auto()
    READY = auto()
    FAILED = auto()
    STOPPED = auto()


@dataclass(frozen=True)
class InstanceStatus:
    """Immutable, indexed lifecycle snapshot for Diagnostics and UI."""

    scenario_index: int
    state: InstanceRuntimeState
    error: str | None = None


class InstanceDiagnostics(LiveSplitBridgeDiagnostics, Protocol):
    """Facts one instance reports while it owns its thread."""

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

    def worker_stopped(self, connection: LiveSplitConnection) -> None: ...

    def scenario_evaluation_failed(
        self,
        scenario_index: int,
        error: Exception,
    ) -> None: ...

    def instance_run_changed(
        self,
        scenario_index: int,
        run_info: LiveSplitRunInfo | None,
    ) -> None: ...

    def instance_evaluated(
        self,
        scenario_index: int,
        context: FrameContext,
        completed_at: MonotonicTime,
    ) -> None: ...


class _Attempt(Enum):
    CONNECTION_LOST = auto()
    TERMINAL = auto()
    STOPPED = auto()


class BridgeEventReceiverLike(Protocol):
    """Receive-side transport contract owned by the instance thread."""

    def start(self) -> None: ...

    def wait_until_started(self) -> None: ...

    def drain(
        self,
    ) -> tuple[BridgeEventConnectionLost | BridgeEventReceived, ...]: ...

    def take_overflow(self) -> bool: ...

    def stop(self) -> None: ...


class InstanceRuntime:
    """Own one scenario's Bridge connection, rules, and evaluation thread."""

    def __init__(
        self,
        scenario_index: int,
        connection: LiveSplitConnection,
        scenario: Scenario,
        *,
        diagnostics: InstanceDiagnostics,
        logger: logging.Logger | logging.LoggerAdapter | None = None,
        receive_timeout_ms: int = DEFAULT_EVENT_RECEIVE_TIMEOUT_MS,
        reconnect_delay_seconds: float = DEFAULT_RECONNECT_DELAY_SECONDS,
        event_capacity: int = DEFAULT_EVENT_CAPACITY,
        rpc_timeout_ms: int = 3000,
        heartbeat_timeout_ms: int = 3000,
        time_provider: TimeProvider | None = None,
        subscriber_factory: Callable[[], BridgeEventSubscriberLike] | None = None,
        adapter_factory: Callable[[], LiveSplitBridgeAdapter] | None = None,
        receiver_factory: (
            Callable[[threading.Event], BridgeEventReceiverLike] | None
        ) = None,
    ) -> None:
        if receive_timeout_ms < 0:
            raise ValueError("receive_timeout_ms must be non-negative")
        if reconnect_delay_seconds < 0:
            raise ValueError("reconnect_delay_seconds must be non-negative")
        if event_capacity <= 0:
            raise ValueError("event capacity must be positive")
        self.scenario_index = scenario_index
        self.scenario = scenario
        self.connection = connection
        self._diagnostics = diagnostics
        self._logger = logger or logging.getLogger(__name__)
        self._receive_timeout_ms = receive_timeout_ms
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._event_capacity = event_capacity
        self._rpc_timeout_ms = rpc_timeout_ms
        self._heartbeat_timeout_ms = heartbeat_timeout_ms
        self._time_provider = time_provider or TimeProvider()
        self._subscriber_factory = subscriber_factory or self._create_subscriber
        self._adapter_factory = adapter_factory or self._create_adapter
        self._receiver_factory = receiver_factory or self._create_receiver

        self._state_lock = threading.RLock()
        self._state = InstanceRuntimeState.CONNECTING
        self._error: Exception | None = None
        self._run_info: LiveSplitRunInfo | None = None
        self._generation = 0
        self._initialized_once = False

        self._frame_lock = threading.Lock()
        self._pending_frame: SharedFrameEvaluation | None = None

        self._wakeup = threading.Event()
        self._stop_requested = threading.Event()

        # Owned exclusively by the instance thread.
        self._scenario_runtime: ScenarioRuntime | None = None
        self._adapter: LiveSplitBridgeAdapter | None = None
        self._receiver: BridgeEventReceiverLike | None = None

        self._log("instance.connecting")

    # -- Public, thread-safe observation -------------------------------------

    @property
    def state(self) -> InstanceRuntimeState:
        with self._state_lock:
            return self._state

    @property
    def error(self) -> Exception | None:
        with self._state_lock:
            return self._error

    @property
    def run_info(self) -> LiveSplitRunInfo | None:
        with self._state_lock:
            return self._run_info

    @property
    def generation(self) -> int:
        with self._state_lock:
            return self._generation

    def status(self) -> InstanceStatus:
        with self._state_lock:
            error = self._error
            return InstanceStatus(
                self.scenario_index,
                self._state,
                str(error) if error is not None else None,
            )

    # -- Frame dispatch ------------------------------------------------------

    def publish_frame(self, shared: SharedFrameEvaluation) -> None:
        """Store the newest frame as the only pending frame and wake the thread."""
        if self._stop_requested.is_set():
            return
        with self._frame_lock:
            self._pending_frame = shared
        self._wakeup.set()

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._wakeup.set()

    def stop(self) -> None:
        """Finalize after the instance thread has been joined."""
        self._scenario_runtime = None
        self._set_run_info(None)
        with self._state_lock:
            self._state = InstanceRuntimeState.STOPPED

    # -- Instance thread -----------------------------------------------------

    def run(self) -> None:
        try:
            self._diagnostics.worker_started(self.connection)
            while not self._stop_requested.is_set():
                outcome = self._run_connection()
                self._release_transport()
                if outcome in (_Attempt.TERMINAL, _Attempt.STOPPED):
                    return
                self._stop_requested.wait(self._reconnect_delay_seconds)
        finally:
            self._release_transport()
            self._finish_run()

    def _create_subscriber(self) -> BridgeEventSubscriber:
        return BridgeEventSubscriber(
            self.connection.event_endpoint,
            heartbeat_timeout_ms=self._heartbeat_timeout_ms,
        )

    def _create_adapter(self) -> LiveSplitBridgeAdapter:
        return LiveSplitBridgeAdapter(
            self.connection,
            diagnostics=self._diagnostics,
            rpc_timeout_ms=self._rpc_timeout_ms,
        )

    def _create_receiver(self, wakeup: threading.Event) -> BridgeEventReceiver:
        return BridgeEventReceiver(
            subscriber_factory=self._subscriber_factory,
            wakeup=wakeup,
            receive_timeout_ms=self._receive_timeout_ms,
            capacity=self._event_capacity,
        )

    def _run_connection(self) -> _Attempt:
        try:
            receiver = self._receiver_factory(self._wakeup)
            receiver.start()
            receiver.wait_until_started()
            self._receiver = receiver
            adapter = self._adapter_factory()
            self._adapter = adapter
            initial = adapter.attach()
        except (BridgeProtocolError, BridgeRemoteError, ValueError) as error:
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeClientError as error:
            self._diagnostics.initial_sync_failed(self.connection, error)
            return _Attempt.CONNECTION_LOST
        except Exception as error:  # noqa: BLE001
            self._fail(error)
            return _Attempt.TERMINAL

        if self._stop_requested.is_set():
            return _Attempt.STOPPED
        if not self._establish(initial):
            return _Attempt.TERMINAL
        return self._serve()

    def _establish(self, initial: LiveSplitUpdate) -> bool:
        try:
            validate_split_count(self.scenario, initial.snapshot)
        except ValueError as error:
            self._set_error(error)
            with self._state_lock:
                self._state = InstanceRuntimeState.FAILED
            self._log("instance.validation_failed", error=str(error))
            return False

        runtime = ScenarioRuntime(self.scenario, logger=self._logger)
        runtime.apply_livesplit_update(initial)
        self._scenario_runtime = runtime
        self._set_run_info(initial.run_info)
        with self._state_lock:
            self._state = InstanceRuntimeState.READY
        if self._initialized_once:
            self._log("instance.reinitialized")
        self._initialized_once = True
        self._log("instance.ready")
        return True

    def _serve(self) -> _Attempt:
        while not self._stop_requested.is_set():
            self._wakeup.clear()
            outcome = self._process()
            if outcome is not None:
                return outcome
            self._wakeup.wait()
        return _Attempt.STOPPED

    def _process(self) -> _Attempt | None:
        receiver = self._receiver
        adapter = self._adapter
        if receiver is None or adapter is None:
            return None
        messages = receiver.drain()
        overflowed = receiver.take_overflow()
        outcome = self._handle_connection_loss(messages)
        if outcome is not None:
            return outcome
        if overflowed:
            # Dropped events make the stream non-contiguous: resynchronize
            # rather than trusting the remaining drained events.
            return self._resync(adapter, LiveSplitResyncReason.EVENT_INBOX_OVERFLOW)
        # Apply every already-received authoritative event before evaluating a
        # frame, so the scenario never evaluates stale LiveSplit state.
        for message in messages:
            if isinstance(message, BridgeEventReceived):
                outcome = self._apply_event(adapter, message.event)
                if outcome is not None:
                    return outcome
        if self.state is not InstanceRuntimeState.READY:
            return None
        shared = self._take_frame()
        if shared is None:
            return None
        return self._evaluate(adapter, shared)

    def _evaluate(
        self,
        adapter: LiveSplitBridgeAdapter,
        shared: SharedFrameEvaluation,
    ) -> _Attempt | None:
        runtime = self._scenario_runtime
        if runtime is None:
            return None
        context = FrameContext(shared=shared)
        try:
            action = runtime.evaluate(context)
        except Exception as error:  # noqa: BLE001
            self._diagnostics.scenario_evaluation_failed(self.scenario_index, error)
            return None
        # Evaluation latency ends the moment evaluate() returned, before any
        # action validity check, late event drain, or RPC.
        completed_at = self._time_provider.now()
        self._publish_observations(context, completed_at)
        if action is None:
            return None
        return self._dispatch_action(adapter, runtime, action)

    def _dispatch_action(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        action: Action,
    ) -> _Attempt | None:
        expected = runtime.current_snapshot
        if expected is None:
            return None
        # Events can arrive while the scenario was evaluating. Apply them before
        # sending the RPC so a now-stale action is rejected locally.
        receiver = self._receiver
        if receiver is not None:
            outcome = self._drain_late_events(adapter, receiver)
            if outcome is not None:
                return outcome
        result = adapter.execute_action(action, expected)
        if result is ActionExecution.NOT_DISPATCHED:
            runtime.action_not_dispatched(action)
        elif result is ActionExecution.UNKNOWN:
            self._connection_lost(BridgeConnectionLostError("action outcome unknown"))
            return _Attempt.CONNECTION_LOST
        return None

    def _drain_late_events(
        self,
        adapter: LiveSplitBridgeAdapter,
        receiver: BridgeEventReceiverLike,
    ) -> _Attempt | None:
        messages = receiver.drain()
        overflowed = receiver.take_overflow()
        outcome = self._handle_connection_loss(messages)
        if outcome is not None:
            return outcome
        if overflowed:
            return self._resync(adapter, LiveSplitResyncReason.EVENT_INBOX_OVERFLOW)
        for message in messages:
            if isinstance(message, BridgeEventReceived):
                outcome = self._apply_event(adapter, message.event)
                if outcome is not None:
                    return outcome
        return None

    def _handle_connection_loss(
        self,
        messages: tuple[BridgeEventConnectionLost | BridgeEventReceived, ...],
    ) -> _Attempt | None:
        for message in messages:
            if isinstance(message, BridgeEventConnectionLost):
                self._connection_lost(message.error)
                return _Attempt.CONNECTION_LOST
        return None

    def _apply_event(
        self,
        adapter: LiveSplitBridgeAdapter,
        event: common_pb2.BridgeEvent,
    ) -> _Attempt | None:
        try:
            received = adapter.handle_event(event)
        except (BridgeProtocolError, BridgeRemoteError, ValueError) as error:
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeClientError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        if received is LiveSplitResyncReason.SESSION_CHANGED:
            self._connection_lost(BridgeConnectionLostError("Bridge session changed"))
            return _Attempt.CONNECTION_LOST
        if isinstance(received, LiveSplitResyncReason):
            return self._resync(adapter, received)
        if received is not None:
            self._apply_update(received)
        return None

    def _resync(
        self,
        adapter: LiveSplitBridgeAdapter,
        reason: LiveSplitResyncReason,
    ) -> _Attempt | None:
        try:
            update = adapter.resync(reason)
        except (BridgeProtocolError, BridgeRemoteError, ValueError) as error:
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeClientError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        self._apply_update(update)
        return None

    def _apply_update(self, update: LiveSplitUpdate) -> None:
        if update.run_info is not None:
            self._set_run_info(update.run_info)
        runtime = self._scenario_runtime
        if runtime is not None:
            runtime.apply_livesplit_update(update)

    def _take_frame(self) -> SharedFrameEvaluation | None:
        with self._frame_lock:
            shared = self._pending_frame
            self._pending_frame = None
            return shared

    def _publish_observations(
        self,
        context: FrameContext,
        completed_at: MonotonicTime,
    ) -> None:
        try:
            self._diagnostics.instance_evaluated(
                self.scenario_index, context, completed_at
            )
        except Exception:  # noqa: BLE001, S110
            # Diagnostics must never break the evaluation cycle.
            pass

    def _connection_lost(self, error: Exception) -> None:
        self._scenario_runtime = None
        self._set_run_info(None)
        with self._state_lock:
            self._state = InstanceRuntimeState.CONNECTING
            self._generation += 1
        self._log("instance.connection_lost")
        self._log("instance.connecting")
        self._diagnostics.connection_lost(self.connection, error)

    def _fail(self, error: Exception) -> None:
        self._set_error(error)
        self._scenario_runtime = None
        self._set_run_info(None)
        with self._state_lock:
            self._state = InstanceRuntimeState.FAILED
        self._log("instance.failed", error=str(error))
        self._diagnostics.initial_sync_failed(self.connection, error)

    def _finish_run(self) -> None:
        self._scenario_runtime = None
        with self._state_lock:
            if self._state is not InstanceRuntimeState.FAILED:
                self._state = InstanceRuntimeState.STOPPED
        self._log("instance.stopped")
        self._diagnostics.worker_stopped(self.connection)

    def _release_transport(self) -> None:
        receiver = self._receiver
        self._receiver = None
        if receiver is not None:
            receiver.stop()
        adapter = self._adapter
        self._adapter = None
        if adapter is not None:
            adapter.close()

    def _set_error(self, error: Exception) -> None:
        with self._state_lock:
            self._error = error

    def _set_run_info(self, run_info: LiveSplitRunInfo | None) -> None:
        with self._state_lock:
            if run_info == self._run_info:
                return
            self._run_info = run_info
        self._diagnostics.instance_run_changed(self.scenario_index, run_info)

    def _log(self, event: str, **fields: object) -> None:
        try:
            self._logger.info(event, extra={"event": event, **fields})
        except Exception:  # noqa: BLE001, S110
            pass
