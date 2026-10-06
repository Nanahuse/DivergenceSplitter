"""Runtime boundary for the official LiveSplit.Bridge client.

This adapter owns only the RPC side of the connection plus the event-sequence
and revision bookkeeping that belongs to the transport. Raw SUB event reception
is performed by :mod:`divergencesplitter_runtime.livesplit.event_receiver` on a
dedicated thread; :meth:`LiveSplitBridgeAdapter.handle_event` validates one
received event against the adapter baseline and converts it to a runtime update.

``event_sequence`` continuity and heartbeat semantics live here, so
``ScenarioRuntime`` only ever sees an authoritative LiveSplit state.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, Self

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import (
    BridgeClientError,
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeRpcClient,
    common_pb2,
)

from divergencesplitter_runtime.livesplit.mapping import (
    event_update_kind,
    run_info_from_proto,
    snapshot_from_timer_state,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitRunInfo,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
    rpc_endpoint,
)


class LiveSplitBridgeDiagnostics(Protocol):
    """Receives Bridge operation facts without raising exceptions to the caller."""

    def snapshot_mismatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None: ...

    def action_precondition_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_succeeded(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_rejected(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None: ...

    def action_result_unknown(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None: ...

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None: ...

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None: ...

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None: ...

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None: ...


class ActionExecution(Enum):
    """How far one action attempt progressed against the local baseline."""

    # Rejected locally before any timer RPC was sent.
    NOT_DISPATCHED = auto()
    # A timer RPC completed and its response was interpreted.
    DISPATCHED = auto()
    # The timer RPC outcome is unknown (timeout / transport failure).
    UNKNOWN = auto()


@dataclass(frozen=True)
class ActionOutcome:
    """The result of one action attempt plus any immediate state update."""

    execution: ActionExecution
    update: LiveSplitUpdate | None = None


# Bound on how many times a newer RunState may force a fresh TimerState while
# trying to pair the two revisions. Never retried without limit.
_MAX_STATE_SYNC_ATTEMPTS = 4


class LiveSplitBridgeAdapter:
    def __init__(
        self,
        connection: LiveSplitConnection,
        *,
        diagnostics: LiveSplitBridgeDiagnostics,
        rpc: BridgeRpcClient | None = None,
        rpc_timeout_ms: int = 3000,
    ) -> None:
        self._connection = connection
        self._diagnostics = diagnostics
        self._rpc = (
            rpc
            if rpc is not None
            else BridgeRpcClient(
                rpc_endpoint(connection),
                response_timeout_ms=rpc_timeout_ms,
            )
        )
        self._closed = False
        self._baseline: LiveSplitSnapshot | None = None
        self._run_info: LiveSplitRunInfo | None = None
        self._last_event_sequence: int | None = None

    def attach(self) -> LiveSplitUpdate:
        response = self._rpc.attach()
        timer_state = response.timer_state
        if response.session_id != timer_state.session_id:
            raise ValueError(
                "Bridge attach response and timer_state session IDs do not match"
            )
        snapshot, run_info = self._consistent_state(timer_state)
        self._baseline = snapshot
        self._last_event_sequence = None
        return LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot, run_info)

    def handle_event(
        self,
        event: common_pb2.BridgeEvent,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        """Validate one raw event against the baseline and convert it."""
        baseline = self._baseline
        if baseline is None:
            raise RuntimeError("attach must complete before receiving Bridge events")

        if event.type == common_pb2.EVENT_HEARTBEAT:
            return self._handle_heartbeat(event, baseline)

        if event.session_id != baseline.session_id:
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.SESSION_CHANGED

        last_sequence = self._last_event_sequence
        if last_sequence is not None:
            if event.event_sequence <= last_sequence:
                # Duplicate or stale event: never re-applied.
                return None
            if event.event_sequence > last_sequence + 1:
                self._diagnostics.gap_detected(
                    self._connection,
                    baseline,
                    event.session_id,
                    event.event_sequence,
                )
                return LiveSplitResyncReason.GAP

        kind = event_update_kind(event.type)

        if not event.HasField("timer_state"):
            raise BridgeProtocolError("Bridge state event has no timer_state")
        timer_state = event.timer_state
        if timer_state.session_id != event.session_id:
            raise BridgeProtocolError(
                "Bridge event and timer_state session IDs do not match"
            )

        if kind is None:
            # Runtime-only change: the protocol validation above still applies,
            # but it advances the cursor without a scenario update.
            self._last_event_sequence = event.event_sequence
            return None

        cached = self._run_info
        if cached is not None and timer_state.run_revision < cached.run_revision:
            # Stale run reference: the event predates the current baseline.
            self._last_event_sequence = event.event_sequence
            return None

        run_info: LiveSplitRunInfo | None
        if cached is not None and timer_state.run_revision == cached.run_revision:
            run_info = None
            snapshot = self._snapshot(timer_state, cached)
        else:
            snapshot, run_info = self._consistent_state(timer_state)

        if (
            last_sequence is None
            and snapshot.state_revision > baseline.state_revision + 1
        ):
            # The initial baseline cannot be reconciled with this first event.
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.GAP

        self._last_event_sequence = event.event_sequence
        if snapshot.state_revision <= baseline.state_revision and run_info is None:
            # Already reflected locally (for example by an OperationResponse) and
            # no run content changed: advance the cursor without re-applying.
            return None

        self._baseline = snapshot
        return LiveSplitUpdate(kind, snapshot, run_info)

    def _handle_heartbeat(
        self,
        event: common_pb2.BridgeEvent,
        baseline: LiveSplitSnapshot,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        self._diagnostics.heartbeat_received(
            self._connection,
            event.session_id,
            event.event_sequence,
        )
        if event.session_id != baseline.session_id:
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.SESSION_CHANGED
        last_sequence = self._last_event_sequence
        if last_sequence is None:
            # No state event has arrived yet. The heartbeat carries the last
            # settled state-event sequence, so it establishes the stream
            # baseline and makes gap detection active from startup.
            self._last_event_sequence = event.event_sequence
            return None
        if event.event_sequence < last_sequence:
            # A heartbeat older than the last settled event.
            return None
        if event.event_sequence > last_sequence:
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.GAP
        return None

    def resync(
        self,
        reason: LiveSplitResyncReason,
        *,
        event_sequence: int | None = None,
    ) -> LiveSplitUpdate:
        previous = self._require_baseline()
        self._diagnostics.resync_started(self._connection, reason)
        timer_state = self._rpc.get_timer_state()
        snapshot, run_info = self._consistent_state(timer_state)
        self._baseline = snapshot
        if event_sequence is not None:
            # Keep the sequence that triggered the resync as the new stream
            # baseline so continuity and heartbeat gap detection stay active.
            self._last_event_sequence = event_sequence
        self._diagnostics.resync_completed(
            self._connection,
            reason,
            previous,
            snapshot,
        )
        return LiveSplitUpdate(LiveSplitUpdateKind.RESYNC, snapshot, run_info)

    def _consistent_state(
        self,
        timer_state: common_pb2.TimerState,
    ) -> tuple[LiveSplitSnapshot, LiveSplitRunInfo]:
        """Pair a TimerState with the RunState of its exact run revision.

        ``get_run()`` can return a RunState whose ``run_revision`` is newer than
        the TimerState that requested it. Mixing the two revisions in a single
        :class:`LiveSplitSnapshot` is forbidden, so a newer RunState forces a
        fresh ``get_timer_state()`` until both agree. A RunState behind the
        TimerState, or a pair that never settles within the bounded number of
        attempts, is a protocol error.
        """
        for _ in range(_MAX_STATE_SYNC_ATTEMPTS):
            run_info = run_info_from_proto(self._rpc.get_run())
            if run_info.session_id != timer_state.session_id:
                raise BridgeProtocolError(
                    "Bridge timer_state and run session IDs do not match"
                )
            if run_info.run_revision == timer_state.run_revision:
                self._run_info = run_info
                return self._snapshot(timer_state, run_info), run_info
            if run_info.run_revision < timer_state.run_revision:
                raise BridgeProtocolError("Bridge run revision is behind timer_state")
            timer_state = self._rpc.get_timer_state()
        raise BridgeProtocolError(
            "Bridge timer_state and run revision did not stabilize"
        )

    @staticmethod
    def _snapshot(
        timer_state: common_pb2.TimerState,
        run_info: LiveSplitRunInfo,
    ) -> LiveSplitSnapshot:
        return snapshot_from_timer_state(
            timer_state,
            split_count=len(run_info.segments),
        )

    def _require_baseline(self) -> LiveSplitSnapshot:
        baseline = self._baseline
        if baseline is None:
            raise RuntimeError("attach must complete before Bridge resynchronization")
        return baseline

    def execute_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
    ) -> ActionOutcome:
        actual_snapshot = self._require_baseline()

        if not self._matches_expected_state(expected_snapshot, actual_snapshot):
            self._diagnostics.snapshot_mismatched(
                self._connection,
                action,
                expected_snapshot,
                actual_snapshot,
            )
            return ActionOutcome(ActionExecution.NOT_DISPATCHED)
        if not self._meets_action_precondition(action, actual_snapshot):
            self._diagnostics.action_precondition_failed(
                self._connection, action, actual_snapshot
            )
            return ActionOutcome(ActionExecution.NOT_DISPATCHED)

        operation: Callable[[], common_pb2.OperationResponse] = {
            "start": self._rpc.start,
            "split": self._rpc.split,
            "skip": self._rpc.skip,
            "undo": self._rpc.undo,
            "reset": self._rpc.reset,
            "pause": self._rpc.pause,
            "resume": self._rpc.resume,
        }[action.operation]
        try:
            response = operation()
        except BridgeRemoteError as error:
            self._diagnostics.action_rejected(
                self._connection,
                action,
                actual_snapshot,
                error.code,
                error.message,
            )
            return ActionOutcome(ActionExecution.DISPATCHED)
        except BridgeProtocolError:
            raise
        except BridgeClientError as error:
            self._diagnostics.action_result_unknown(
                self._connection, action, actual_snapshot, error
            )
            return ActionOutcome(ActionExecution.UNKNOWN)

        if not response.success:
            self._diagnostics.action_rejected(
                self._connection,
                action,
                actual_snapshot,
                None,
                response.message,
            )
            return ActionOutcome(ActionExecution.DISPATCHED)
        if not response.HasField("timer_state"):
            raise BridgeProtocolError(
                "successful timer operation response did not contain a timer_state"
            )
        timer_state = response.timer_state
        if timer_state.session_id != actual_snapshot.session_id:
            raise BridgeProtocolError(
                "operation response session changed underneath the adapter"
            )
        cached = self._run_info
        if cached is not None and timer_state.run_revision < cached.run_revision:
            raise BridgeProtocolError(
                "operation response run revision regressed behind timer_state"
            )
        run_info: LiveSplitRunInfo | None
        if cached is not None and timer_state.run_revision == cached.run_revision:
            run_info = None
            snapshot = self._snapshot(timer_state, cached)
        else:
            snapshot, run_info = self._consistent_state(timer_state)
        self._baseline = snapshot
        self._diagnostics.action_succeeded(self._connection, action, snapshot)
        return ActionOutcome(
            ActionExecution.DISPATCHED,
            LiveSplitUpdate(LiveSplitUpdateKind.TRANSITION, snapshot, run_info),
        )

    @staticmethod
    def _matches_expected_state(
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> bool:
        return (
            expected.session_id == actual.session_id
            and expected.state_revision == actual.state_revision
            and expected.phase is actual.phase
            and expected.split_index == actual.split_index
            and expected.split_count == actual.split_count
        )

    @staticmethod
    def _meets_action_precondition(
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> bool:
        if action.operation == "split":
            return snapshot.phase is TimerPhase.RUNNING
        if action.operation == "start":
            return snapshot.phase is TimerPhase.NOT_RUNNING
        if action.operation == "skip":
            return (
                snapshot.phase is TimerPhase.RUNNING
                and snapshot.split_index < snapshot.split_count - 1
            )
        if action.operation == "undo":
            return snapshot.phase is TimerPhase.ENDED or (
                snapshot.phase in (TimerPhase.RUNNING, TimerPhase.PAUSED)
                and snapshot.split_index > 0
            )
        if action.operation == "reset":
            return snapshot.phase in (
                TimerPhase.RUNNING,
                TimerPhase.PAUSED,
                TimerPhase.ENDED,
            )
        if action.operation == "pause":
            return snapshot.phase is TimerPhase.RUNNING
        return snapshot.phase is TimerPhase.PAUSED

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._rpc.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
