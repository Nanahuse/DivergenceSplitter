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

from divergencesplitter import (
    Action,
    LiveSplitConnection,
    MonotonicTime,
    ThreadTimeProvider,
)
from divergencesplitter.clock import TimeProvider
from divergencesplitter.frame.models import FrameContext, SharedFrameEvaluation
from divergencesplitter.scenario.models import Scenario
from livesplit_bridge import (
    BridgeClientError,
    BridgeConnectionLostError,
    BridgeEvent,
    BridgeEventSubscriber,
    BridgeProtocolError,
    BridgeRemoteError,
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
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
    event_endpoint,
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
        evaluation_cpu_duration_ns: int,
        evaluation_wall_duration_ns: int,
    ) -> None: ...

    def instance_reset(self, scenario_index: int) -> None: ...

    def reaction_measured(
        self,
        scenario_index: int,
        action: Action,
        target_ns: int,
        actual_ns: int,
        lateness_ns: int,
    ) -> None: ...

    def action_cancelled(
        self,
        scenario_index: int,
        action: Action,
        reason: str,
    ) -> None: ...


class _Attempt(Enum):
    CONNECTION_LOST = auto()
    TERMINAL = auto()
    STOPPED = auto()


class _ReactionResult(Enum):
    OK = auto()
    CANCELLED = auto()


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
        reaction_time_ms: int = 0,
        time_provider: TimeProvider | None = None,
        cpu_time_provider: ThreadTimeProvider | None = None,
        reaction_wait: Callable[[int], None] | None = None,
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
        if type(reaction_time_ms) is not int or reaction_time_ms < 0:
            raise ValueError("reaction_time_ms must be a non-negative integer")
        self.scenario_index = scenario_index
        self.scenario = scenario
        self.connection = connection
        self._diagnostics = diagnostics
        self._logger = logger or logging.getLogger(__name__)
        self._receive_timeout_ms = receive_timeout_ms
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._event_capacity = event_capacity
        self._rpc_timeout_ms = rpc_timeout_ms
        self._reaction_time_ns = reaction_time_ms * 1_000_000
        self._time_provider = time_provider or TimeProvider()
        self._cpu_time_provider = cpu_time_provider or ThreadTimeProvider()
        self._reaction_wait = reaction_wait or self._wait_for_reaction
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
        # Instance-thread only: captured_at of the frame already checked for an
        # automatic Reset during the current reaction wait.
        self._reaction_reset_checked_at: int | None = None

        self._wakeup = threading.Event()
        self._stop_requested = threading.Event()
        # A pending manual Reset request is consumed by the instance thread,
        # never executed on the requesting (UI) thread. It carries no snapshot:
        # the decision uses whatever LiveSplit state is current when processed.
        self._manual_reset_requested = threading.Event()

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

    def request_reset(self) -> None:
        """Queue one manual Reset for the instance thread to decide.

        No Bridge RPC happens here. The request only flags a pending manual
        Reset and wakes the worker, which evaluates the Reset precondition
        against the latest LiveSplit snapshot on its own thread. A request that
        is never processed before teardown or reconnect is dropped rather than
        replayed against a later connection.
        """

        if self._stop_requested.is_set():
            return
        self._manual_reset_requested.set()
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
            event_endpoint(self.connection),
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
            initial = adapter.synchronize()
        except BridgeProtocolError as error:
            self._diagnostics.initial_sync_failed(self.connection, error)
            return _Attempt.CONNECTION_LOST
        except (BridgeRemoteError, ValueError) as error:
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
        initial = self._prime_initial_events(adapter, initial)
        if isinstance(initial, _Attempt):
            return initial
        if not self._establish(initial):
            return _Attempt.TERMINAL
        return self._serve()

    def _prime_initial_events(
        self,
        adapter: LiveSplitBridgeAdapter,
        initial: LiveSplitUpdate,
    ) -> LiveSplitUpdate | _Attempt:
        """Settle the initial RPC baseline after discarding in-flight old events."""
        receiver = self._receiver
        if receiver is None:
            return initial
        for _ in range(5):
            messages = receiver.drain()
            overflowed = receiver.take_overflow()
            outcome = self._handle_connection_loss(messages)
            if outcome is not None:
                return outcome
            if overflowed:
                self._connection_lost(
                    BridgeConnectionLostError(
                        "event inbox overflow during initial sync"
                    )
                )
                return _Attempt.CONNECTION_LOST
            events = tuple(
                message.event
                for message in messages
                if isinstance(message, BridgeEventReceived)
            )
            if any(event.session_id != initial.session_id for event in events):
                self._connection_lost(
                    BridgeConnectionLostError(
                        "Bridge session changed during initial sync"
                    )
                )
                return _Attempt.CONNECTION_LOST
            if not events:
                return initial
            # Events arrived during the query window: their TimerState cannot be
            # applied atomically against the just-read baseline, so discard them
            # and re-read TimerState and Run instead of guessing the ordering.
            adapter.establish_event_cursor(events)
            try:
                initial = adapter.synchronize()
            except BridgeProtocolError as error:
                self._diagnostics.initial_sync_failed(self.connection, error)
                return _Attempt.CONNECTION_LOST
            except (BridgeRemoteError, ValueError) as error:
                self._fail(error)
                return _Attempt.TERMINAL
            except BridgeClientError as error:
                self._diagnostics.initial_sync_failed(self.connection, error)
                return _Attempt.CONNECTION_LOST
        # The baseline never settled within the retry budget. Never claim READY
        # on an unconfirmed state; reconnect instead of looping without limit.
        self._log("bridge.initial_sync_unsettled")
        self._connection_lost(
            BridgeConnectionLostError("initial synchronization did not converge")
        )
        return _Attempt.CONNECTION_LOST

    def _establish(self, initial: LiveSplitUpdate) -> bool:
        # A manual Reset requested before this connection existed is not carried
        # over: once connected, only a fresh request may Reset.
        self._manual_reset_requested.clear()
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
        self._log(
            "instance.ready",
            session_id=initial.session_id,
            event_sequence=initial.event_sequence,
            state_epoch=initial.state_epoch,
            phase=initial.snapshot.phase.name,
            split_index=initial.snapshot.split_index,
        )
        return True

    def _serve(self) -> _Attempt:
        while not self._stop_requested.is_set():
            self._wakeup.clear()
            outcome = self._process()
            if outcome is not None:
                return outcome
            runtime = self._scenario_runtime
            deadline_ns = None if runtime is None else runtime.state_wait_deadline_ns
            if deadline_ns is None:
                self._wakeup.wait()
            else:
                remaining_ns = deadline_ns - self._time_provider.now().nanoseconds
                self._wakeup.wait(max(0, remaining_ns) / 1_000_000_000)
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
            # Dropped events make the stream non-contiguous and the sequence
            # cannot be reconciled with a query, so rebuild both connections.
            self._connection_lost(BridgeConnectionLostError("event inbox overflow"))
            return _Attempt.CONNECTION_LOST
        # Apply every already-received authoritative event before evaluating a
        # frame, so the scenario never evaluates stale LiveSplit state.
        for message in messages:
            if isinstance(message, BridgeEventReceived):
                outcome = self._apply_event(adapter, message.event)
                if outcome is not None:
                    return outcome
        if self._manual_reset_requested.is_set():
            # Consume the request even when the phase forbids a Reset: a stale
            # request must never survive into a later state.
            self._manual_reset_requested.clear()
            outcome = self._handle_manual_reset(adapter)
            if outcome is not None:
                return outcome
        if self.state is not InstanceRuntimeState.READY:
            return None
        outcome = self._process_state_wait_timeout(adapter)
        if outcome is not None:
            return outcome
        shared = self._take_frame()
        if shared is None:
            return None
        return self._evaluate(adapter, shared)

    def _process_state_wait_timeout(
        self,
        adapter: LiveSplitBridgeAdapter,
    ) -> _Attempt | None:
        runtime = self._scenario_runtime
        if runtime is None:
            return None
        deadline_ns = runtime.state_wait_deadline_ns
        now_ns = self._time_provider.now().nanoseconds
        if deadline_ns is None or now_ns < deadline_ns:
            return None
        try:
            update = adapter.confirm_timer_state()
        except BridgeProtocolError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        except (BridgeRemoteError, ValueError) as error:
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeClientError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        self._apply_update(update)
        completed_at_ns = self._time_provider.now().nanoseconds
        self._discard_frames_through(completed_at_ns)
        if runtime.state_wait_deadline_ns is not None:
            runtime.state_wait_timed_out(completed_at_ns)
            self._log(
                "bridge.state_wait_timeout",
                session_id=adapter.session_id,
                event_sequence=adapter.event_sequence,
                state_epoch=adapter.state_epoch,
                phase=update.snapshot.phase.name,
                split_index=update.snapshot.split_index,
            )
        return None

    def _evaluate(
        self,
        adapter: LiveSplitBridgeAdapter,
        shared: SharedFrameEvaluation,
    ) -> _Attempt | None:
        runtime = self._scenario_runtime
        if runtime is None:
            return None
        context = FrameContext(shared=shared)
        evaluation_wall_started_at = self._time_provider.now()
        evaluation_cpu_started_at = self._cpu_time_provider.now()
        try:
            action = runtime.evaluate(context)
        except Exception as error:  # noqa: BLE001
            self._diagnostics.scenario_evaluation_failed(self.scenario_index, error)
            return None
        # Evaluation ends the moment evaluate() returned, before any action
        # validity check, late event drain, reaction wait, or RPC. The reported
        # value is the thread CPU time the instance actually spent evaluating;
        # wall-clock time the thread was stopped is kept only for investigation.
        evaluation_cpu_completed_at = self._cpu_time_provider.now()
        evaluation_wall_completed_at = self._time_provider.now()
        evaluation_cpu_duration_ns = (
            evaluation_cpu_completed_at.nanoseconds
            - evaluation_cpu_started_at.nanoseconds
        )
        evaluation_wall_duration_ns = (
            evaluation_wall_completed_at.nanoseconds
            - evaluation_wall_started_at.nanoseconds
        )
        self._publish_observations(
            context,
            evaluation_wall_completed_at,
            evaluation_cpu_duration_ns,
            evaluation_wall_duration_ns,
        )
        if action is not None and action.operation == "start":
            # A new Start decision begins a fresh evaluation period.
            self._publish_reset()
        if action is None:
            return None
        return self._dispatch_action(adapter, runtime, action, context)

    def _handle_manual_reset(
        self,
        adapter: LiveSplitBridgeAdapter,
    ) -> _Attempt | None:
        # A manual Reset is decided on the instance thread against the current
        # snapshot and is never delayed by reaction_time. Phases that cannot be
        # Reset are a normal no-op.
        runtime = self._scenario_runtime
        if runtime is None:
            return None
        expected = runtime.current_snapshot
        if expected is None:
            return None
        if expected.phase not in (
            TimerPhase.RUNNING,
            TimerPhase.PAUSED,
            TimerPhase.ENDED,
        ):
            return None
        if runtime.reset_pending is not None:
            return None
        action = Action("reset")
        runtime.external_action_pending(action, self._time_provider.now().nanoseconds)
        return self._dispatch_reset(adapter, runtime, action)

    def _dispatch_reset(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        action: Action,
    ) -> _Attempt | None:
        expected = runtime.current_snapshot
        if expected is None:
            runtime.action_not_dispatched(action)
            return None
        return self._execute_control(
            adapter,
            runtime,
            action,
            expected,
            runtime.state_epoch,
        )

    def _dispatch_action(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        action: Action,
        context: FrameContext,
    ) -> _Attempt | None:
        # The expected state is fixed the moment the action was decided; a
        # reaction wait must never let a newer LiveSplit state drift under it
        # without a matching follow or cancellation.
        expected = runtime.current_snapshot
        if expected is None:
            return None
        expected_state_epoch = runtime.state_epoch
        captured_at_ns = context.frame.captured_at.nanoseconds
        if self._reaction_time_ns <= 0:
            receiver = self._receiver
            if receiver is not None:
                outcome = self._drain_late_events(adapter, receiver)
                if outcome is not None:
                    return outcome
            return self._execute(
                adapter,
                runtime,
                action,
                expected,
                expected_state_epoch,
                captured_at_ns,
            )
        return self._dispatch_after_reaction(
            adapter, runtime, action, expected, expected_state_epoch, captured_at_ns
        )

    def _dispatch_after_reaction(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        action: Action,
        expected: LiveSplitSnapshot,
        expected_state_epoch: int,
        captured_at_ns: int,
    ) -> _Attempt | None:
        due_at_ns = captured_at_ns + self._reaction_time_ns
        receiver = self._receiver
        self._reaction_reset_checked_at = None
        while True:
            if self._stop_requested.is_set():
                self._publish_cancel(action, "stop")
                return _Attempt.STOPPED
            # A manual or automatic Reset during the reaction wait cancels the
            # unsent normal action and takes priority over it.
            handled, outcome = self._reaction_reset_priority(adapter, runtime)
            if handled:
                return outcome
            remaining_ns = due_at_ns - self._time_provider.now().nanoseconds
            if remaining_ns <= 0:
                break
            # Interruptible wait: a Bridge event, connection loss, frame, or
            # stop wakes it. Frames stay latest-only and are only consulted for
            # Reset priority, never evaluated as normal action input here.
            self._wakeup.clear()
            self._reaction_wait(remaining_ns)
            if self._stop_requested.is_set():
                self._publish_cancel(action, "stop")
                return _Attempt.STOPPED
            if receiver is None:
                continue
            result, expected, outcome = self._process_reaction_events(
                adapter, runtime, receiver, expected
            )
            if outcome is not None:
                return outcome
            if result is _ReactionResult.CANCELLED:
                self._publish_cancel(action, "event")
                return None
        # Final priority check just before the Control is sent.
        handled, outcome = self._reaction_reset_priority(adapter, runtime)
        if handled:
            return outcome
        if receiver is not None:
            result, expected, outcome = self._process_reaction_events(
                adapter, runtime, receiver, expected
            )
            if outcome is not None:
                return outcome
            if result is _ReactionResult.CANCELLED:
                self._publish_cancel(action, "event")
                return None
        return self._execute(
            adapter,
            runtime,
            action,
            expected,
            expected_state_epoch,
            captured_at_ns,
        )

    def _reaction_reset_priority(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
    ) -> tuple[bool, _Attempt | None]:
        """Give a pending Reset priority over the unsent normal action.

        Returns ``(handled, outcome)``. When ``handled`` is true the reaction
        wait must end and ``outcome`` (possibly ``None``) is returned.
        """
        if self._manual_reset_requested.is_set():
            self._manual_reset_requested.clear()
            self._cancel_unsent(runtime, "reset")
            return True, self._handle_manual_reset(adapter)
        shared = self._peek_frame()
        if shared is None:
            return False, None
        captured_at_ns = shared.frame.captured_at.nanoseconds
        if captured_at_ns == self._reaction_reset_checked_at:
            return False, None
        self._reaction_reset_checked_at = captured_at_ns
        reset_action = runtime.evaluate_reset_only(FrameContext(shared=shared))
        if reset_action is None:
            # The frame was consulted only for Reset; leave it as the latest
            # pending frame for the normal decision that follows.
            return False, None
        # Reset wins: consume the frame so it is never reused for the normal
        # action, then execute it without a reaction delay.
        self._take_frame()
        return True, self._dispatch_reset(adapter, runtime, reset_action)

    def _cancel_unsent(self, runtime: ScenarioRuntime, reason: str) -> None:
        cancelled = runtime.cancel_pending_action()
        if cancelled is not None:
            self._publish_cancel(cancelled, reason)

    def _process_reaction_events(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        receiver: BridgeEventReceiverLike,
        expected: LiveSplitSnapshot,
    ) -> tuple[_ReactionResult, LiveSplitSnapshot, _Attempt | None]:
        messages = receiver.drain()
        overflowed = receiver.take_overflow()
        for message in messages:
            if isinstance(message, BridgeEventConnectionLost):
                self._connection_lost(message.error)
                return _ReactionResult.CANCELLED, expected, _Attempt.CONNECTION_LOST
        if overflowed:
            self._connection_lost(BridgeConnectionLostError("event inbox overflow"))
            return _ReactionResult.CANCELLED, expected, _Attempt.CONNECTION_LOST
        for message in messages:
            if not isinstance(message, BridgeEventReceived):
                continue
            result, expected, outcome = self._reaction_apply_event(
                adapter, runtime, message.event, expected
            )
            if result is not _ReactionResult.OK or outcome is not None:
                return result, expected, outcome
        return _ReactionResult.OK, expected, None

    def _reaction_apply_event(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        event: BridgeEvent,
        expected: LiveSplitSnapshot,
    ) -> tuple[_ReactionResult, LiveSplitSnapshot, _Attempt | None]:
        try:
            received = adapter.handle_event(event)
        except BridgeProtocolError as error:
            self._connection_lost(error)
            return _ReactionResult.CANCELLED, expected, _Attempt.CONNECTION_LOST
        except (BridgeRemoteError, ValueError) as error:
            self._fail(error)
            return _ReactionResult.CANCELLED, expected, _Attempt.TERMINAL
        except BridgeClientError as error:
            self._connection_lost(error)
            return _ReactionResult.CANCELLED, expected, _Attempt.CONNECTION_LOST
        if received is None:
            return _ReactionResult.OK, expected, None
        if isinstance(received, LiveSplitResyncReason):
            self._connection_lost(
                BridgeConnectionLostError("Bridge event stream integrity lost")
            )
            return _ReactionResult.CANCELLED, expected, _Attempt.CONNECTION_LOST
        self._apply_update(received)
        current = runtime.current_snapshot
        if (
            current is not None
            and received.kind
            in (LiveSplitUpdateKind.PERIODIC, LiveSplitUpdateKind.RUN_CHANGED)
            and not received.run_structure_changed
            and current == received.snapshot
        ):
            # Timing/context-only Run updates do not invalidate timer decisions.
            return _ReactionResult.OK, current, None
        # TRANSITION (manual split, reset, ...) or a rejected periodic update
        # changes the authoritative state: never send the stale action.
        return _ReactionResult.CANCELLED, expected, None

    def _execute(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        action: Action,
        expected: LiveSplitSnapshot,
        expected_state_epoch: int,
        captured_at_ns: int,
    ) -> _Attempt | None:
        self._publish_reaction(action, captured_at_ns)
        return self._execute_control(
            adapter, runtime, action, expected, expected_state_epoch
        )

    def _execute_control(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
        action: Action,
        expected: LiveSplitSnapshot,
        expected_state_epoch: int,
    ) -> _Attempt | None:
        # A Control that may already have reached LiveSplit must never be
        # resent; ambiguous results always recover through reconnection.
        try:
            result = adapter.execute_action(action, expected, expected_state_epoch)
        except BridgeProtocolError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        except BridgeClientError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        except Exception as error:  # noqa: BLE001
            self._fail(error)
            return _Attempt.TERMINAL
        if result.execution is ActionExecution.NOT_DISPATCHED:
            runtime.action_not_dispatched(action)
        elif result.execution is ActionExecution.REJECTED:
            if action.operation == "reset":
                # A rejected Reset is not authoritative: read the current timer
                # state and resume judgment from it. Never resend the Reset.
                return self._reconcile_rejected_reset(adapter, runtime)
            runtime.action_not_dispatched(action)
        elif result.execution is ActionExecution.FAILED:
            self._fail(result.error or RuntimeError("Bridge control failed"))
            return _Attempt.TERMINAL
        elif result.execution is ActionExecution.UNKNOWN:
            self._connection_lost(BridgeConnectionLostError("action outcome unknown"))
            return _Attempt.CONNECTION_LOST
        else:
            runtime.action_accepted(action, self._time_provider.now().nanoseconds)
            if action.operation == "reset":
                # A dispatched Reset begins a fresh evaluation period.
                self._publish_reset()
        return None

    def _reconcile_rejected_reset(
        self,
        adapter: LiveSplitBridgeAdapter,
        runtime: ScenarioRuntime,
    ) -> _Attempt | None:
        # The LiveSplit state after a rejected Reset is authoritative. A
        # transient query failure (INVALID/session change/timeout/connection)
        # recovers by reconnecting; a protocol or value fault is terminal.
        try:
            update = adapter.confirm_timer_state()
        except BridgeRemoteError as error:
            if error.code == "internal_error":
                self._connection_lost(error)
                return _Attempt.CONNECTION_LOST
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeProtocolError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        except ValueError as error:
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeClientError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        completed_at_ns = self._time_provider.now().nanoseconds
        runtime.settle_rejected_reset(update)
        self._discard_frames_through(completed_at_ns)
        self._log(
            "bridge.reset_rejected_reconciled",
            session_id=adapter.session_id,
            event_sequence=adapter.event_sequence,
            state_epoch=adapter.state_epoch,
            phase=update.snapshot.phase.name,
            split_index=update.snapshot.split_index,
        )
        return None

    def _wait_for_reaction(self, timeout_ns: int) -> None:
        self._wakeup.wait(timeout_ns / 1_000_000_000)

    def _publish_reaction(self, action: Action, captured_at_ns: int) -> None:
        actual_ns = self._time_provider.now().nanoseconds - captured_at_ns
        lateness_ns = max(0, actual_ns - self._reaction_time_ns)
        try:
            self._diagnostics.reaction_measured(
                self.scenario_index,
                action,
                self._reaction_time_ns,
                actual_ns,
                lateness_ns,
            )
        except Exception:  # noqa: BLE001, S110
            pass

    def _publish_cancel(self, action: Action, reason: str) -> None:
        try:
            self._diagnostics.action_cancelled(self.scenario_index, action, reason)
        except Exception:  # noqa: BLE001, S110
            pass

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
            self._connection_lost(BridgeConnectionLostError("event inbox overflow"))
            return _Attempt.CONNECTION_LOST
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
        event: BridgeEvent,
    ) -> _Attempt | None:
        try:
            received = adapter.handle_event(event)
        except BridgeProtocolError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        except (BridgeRemoteError, ValueError) as error:
            self._fail(error)
            return _Attempt.TERMINAL
        except BridgeClientError as error:
            self._connection_lost(error)
            return _Attempt.CONNECTION_LOST
        if received is None:
            return None
        if isinstance(received, LiveSplitResyncReason):
            # Gap, session change, or any other integrity loss is recovered by
            # discarding both connections, never by a query-only resync.
            self._connection_lost(
                BridgeConnectionLostError("Bridge event stream integrity lost")
            )
            return _Attempt.CONNECTION_LOST
        self._apply_update(received)
        return None

    def _apply_update(self, update: LiveSplitUpdate) -> None:
        if update.run_info is not None:
            self._set_run_info(update.run_info)
        runtime = self._scenario_runtime
        if runtime is not None:
            runtime.apply_livesplit_update(update)
        if update.kind is LiveSplitUpdateKind.TRANSITION or (
            update.kind is LiveSplitUpdateKind.RUN_CHANGED
            and update.run_structure_changed
        ):
            self._discard_frames_through(self._time_provider.now().nanoseconds)

    def _peek_frame(self) -> SharedFrameEvaluation | None:
        with self._frame_lock:
            return self._pending_frame

    def _take_frame(self) -> SharedFrameEvaluation | None:
        with self._frame_lock:
            shared = self._pending_frame
            self._pending_frame = None
            return shared

    def _discard_frames_through(self, captured_at_ns: int) -> None:
        with self._frame_lock:
            frame = self._pending_frame
            if (
                frame is not None
                and frame.frame.captured_at.nanoseconds <= captured_at_ns
            ):
                self._pending_frame = None

    def _publish_observations(
        self,
        context: FrameContext,
        completed_at: MonotonicTime,
        evaluation_cpu_duration_ns: int,
        evaluation_wall_duration_ns: int,
    ) -> None:
        try:
            self._diagnostics.instance_evaluated(
                self.scenario_index,
                context,
                completed_at,
                evaluation_cpu_duration_ns,
                evaluation_wall_duration_ns,
            )
        except Exception:  # noqa: BLE001, S110
            # Diagnostics must never break the evaluation cycle.
            pass

    def _publish_reset(self) -> None:
        try:
            self._diagnostics.instance_reset(self.scenario_index)
        except Exception:  # noqa: BLE001, S110
            # Diagnostics must never break the evaluation cycle.
            pass

    def _connection_lost(self, error: Exception) -> None:
        self._manual_reset_requested.clear()
        self._scenario_runtime = None
        self._set_run_info(None)
        with self._state_lock:
            self._state = InstanceRuntimeState.CONNECTING
            self._generation += 1
        self._log("instance.connection_lost")
        self._log("instance.connecting")
        self._diagnostics.connection_lost(self.connection, error)

    def _fail(self, error: Exception) -> None:
        self._manual_reset_requested.clear()
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
        self._manual_reset_requested.clear()
        # Discard any frame captured before the connections were rebuilt so
        # judgment resumes from frames captured after reconnection.
        with self._frame_lock:
            self._pending_frame = None
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
