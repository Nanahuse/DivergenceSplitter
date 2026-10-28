"""Protocol v4 transport adapter for one LiveSplit Bridge connection."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, Self

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import (
    BridgeClientError,
    BridgeEvent,
    BridgeProtocolError,
    BridgeReconnectRequiredError,
    BridgeRemoteError,
    BridgeRpcClient,
    EventType,
)

from divergencesplitter_runtime.livesplit.mapping import (
    event_update_kind,
    run_info_from_run,
    snapshot_from_timer_state,
    transition_reason_from_event,
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

_UINT32_MAX = 2**32 - 1


class LiveSplitBridgeDiagnostics(Protocol):
    """Receives Bridge operation facts without raising exceptions to the caller."""

    def action_dispatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        session_id: int | None,
        event_sequence: int | None,
        state_epoch: int,
    ) -> None: ...

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
        code: str | None,
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


class ActionExecution(Enum):
    NOT_DISPATCHED = auto()
    DISPATCHED = auto()
    REJECTED = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class ActionOutcome:
    execution: ActionExecution
    error: Exception | None = None


def _next_sequence(sequence: int) -> int:
    return 1 if sequence == _UINT32_MAX else sequence + 1


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
        self._session_id: int | None = None
        self._baseline: LiveSplitSnapshot | None = None
        self._run_info: LiveSplitRunInfo | None = None
        self._last_event_sequence: int | None = None
        self._state_epoch = 0

    @property
    def session_id(self) -> int | None:
        return self._session_id

    @property
    def event_sequence(self) -> int | None:
        return self._last_event_sequence

    @property
    def state_epoch(self) -> int:
        return self._state_epoch

    @property
    def current_snapshot(self) -> LiveSplitSnapshot | None:
        return self._baseline

    @property
    def current_run_info(self) -> LiveSplitRunInfo | None:
        return self._run_info

    def synchronize(self) -> LiveSplitUpdate:
        """Read the minimal initial TimerState and Run from one RPC session."""

        timer_state = self._rpc.get_timer_state()
        session_id = self._check_rpc_session()
        run_info = run_info_from_run(self._rpc.get_run())
        self._check_rpc_session(session_id)
        snapshot = snapshot_from_timer_state(
            timer_state,
            split_count=len(run_info.segments),
        )
        self._session_id = session_id
        self._run_info = run_info
        self._baseline = snapshot
        self._state_epoch += 1
        return LiveSplitUpdate(
            kind=LiveSplitUpdateKind.INITIAL,
            snapshot=snapshot,
            run_info=run_info,
            session_id=session_id,
            event_sequence=self._last_event_sequence,
            state_epoch=self._state_epoch,
        )

    def establish_event_cursor(self, events: tuple[BridgeEvent, ...]) -> None:
        """Discard events received during initial queries and retain their cursor.

        The follow-up synchronization done by the worker establishes the baseline
        after these events, so applying their TimerState would replay an unknown
        portion of the query/event race.
        """

        matching = [event for event in events if event.session_id == self._session_id]
        if matching:
            previous = self._last_event_sequence
            for event in matching:
                if previous is not None and event.event_sequence != _next_sequence(
                    previous
                ):
                    self._diagnostics.gap_detected(
                        self._connection,
                        self._require_baseline(),
                        event.session_id,
                        event.event_sequence,
                    )
                previous = event.event_sequence
            self._last_event_sequence = matching[-1].event_sequence

    def handle_event(
        self,
        event: BridgeEvent,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        baseline = self._require_baseline()
        session_id = self._session_id
        assert session_id is not None
        if event.session_id != session_id:
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.SESSION_CHANGED

        last_sequence = self._last_event_sequence
        if last_sequence is not None and event.event_sequence != _next_sequence(
            last_sequence
        ):
            # A duplicate, an already-seen sequence, and a missing event all
            # make the authoritative stream non-contiguous.
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.GAP

        event_type = event.type
        kind = event_update_kind(event_type)
        self._last_event_sequence = event.event_sequence
        if kind is None:
            return None

        run_info = self._run_info
        structure_changed = False
        transition = None
        if kind is LiveSplitUpdateKind.RUN_CHANGED:
            run_info = run_info_from_run(self._rpc.get_run())
            self._check_rpc_session(session_id)
            previous_run = self._run_info
            structure_changed = (
                previous_run is None or run_info.structure != previous_run.structure
            )
            self._run_info = run_info
            if len(run_info.segments) != baseline.split_count:
                snapshot = snapshot_from_timer_state(
                    self._rpc.get_timer_state(),
                    split_count=len(run_info.segments),
                )
                self._check_rpc_session(session_id)
            else:
                snapshot = LiveSplitSnapshot(
                    baseline.phase,
                    baseline.split_index,
                    len(run_info.segments),
                )
        else:
            timer_state = event.timer_state
            if timer_state is None:
                if event_type is not EventType.TIMER_RESET:
                    raise BridgeProtocolError("Bridge timer event has no timer_state")
                # Reset can arrive without a captured TimerState; read the
                # authoritative state instead of inferring it from the event.
                timer_state = self._rpc.get_timer_state()
                self._check_rpc_session(session_id)
            assert run_info is not None
            snapshot = snapshot_from_timer_state(
                timer_state,
                split_count=len(run_info.segments),
            )
            transition = transition_reason_from_event(event_type, snapshot)

        self._baseline = snapshot
        if kind is not LiveSplitUpdateKind.RUN_CHANGED or structure_changed:
            self._state_epoch += 1
        return LiveSplitUpdate(
            kind=kind,
            snapshot=snapshot,
            run_info=run_info if kind is LiveSplitUpdateKind.RUN_CHANGED else None,
            session_id=session_id,
            event_sequence=event.event_sequence,
            state_epoch=self._state_epoch,
            run_structure_changed=structure_changed,
            transition=transition,
        )

    def confirm_timer_state(self) -> LiveSplitUpdate:
        """Query only the timer after a control state-wait deadline."""

        baseline = self._require_baseline()
        session_id = self._session_id
        assert session_id is not None
        timer_state = self._rpc.get_timer_state()
        self._check_rpc_session(session_id)
        run_info = self._run_info
        assert run_info is not None
        snapshot = snapshot_from_timer_state(
            timer_state,
            split_count=len(run_info.segments),
        )
        self._baseline = snapshot
        self._state_epoch += 1
        kind = (
            LiveSplitUpdateKind.PERIODIC
            if snapshot == baseline
            else LiveSplitUpdateKind.TRANSITION
        )
        return LiveSplitUpdate(
            kind=kind,
            snapshot=snapshot,
            session_id=session_id,
            event_sequence=self._last_event_sequence,
            state_epoch=self._state_epoch,
        )

    def execute_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
        expected_state_epoch: int,
    ) -> ActionOutcome:
        actual_snapshot = self._require_baseline()
        if (
            expected_state_epoch != self._state_epoch
            or expected_snapshot != actual_snapshot
        ):
            self._diagnostics.snapshot_mismatched(
                self._connection,
                action,
                expected_snapshot,
                actual_snapshot,
            )
            return ActionOutcome(ActionExecution.NOT_DISPATCHED)
        if not self._meets_action_precondition(action, actual_snapshot):
            self._diagnostics.action_precondition_failed(
                self._connection,
                action,
                actual_snapshot,
            )
            return ActionOutcome(ActionExecution.NOT_DISPATCHED)

        operation: Callable[[], None] = {
            "start": self._rpc.start,
            "split": self._rpc.split,
            "skip": self._rpc.skip,
            "undo": self._rpc.undo,
            "reset": self._rpc.reset,
            "pause": self._rpc.pause,
            "resume": self._rpc.resume,
        }[action.operation]
        self._diagnostics.action_dispatched(
            self._connection,
            action,
            actual_snapshot,
            self._session_id,
            self._last_event_sequence,
            self._state_epoch,
        )
        try:
            operation()
        except BridgeRemoteError as error:
            # A RemoteError still commits the RPC session, so a session change
            # here means the rejection came from a different LiveSplit session.
            if self._rpc.session_change is not None:
                self._diagnostics.action_result_unknown(
                    self._connection,
                    action,
                    actual_snapshot,
                    error,
                )
                return ActionOutcome(ActionExecution.UNKNOWN)
            self._diagnostics.action_rejected(
                self._connection,
                action,
                actual_snapshot,
                error.code,
                error.message,
            )
            return ActionOutcome(ActionExecution.REJECTED)
        except BridgeClientError as error:
            # The control may already have executed, so it must never be
            # resent. Communication faults and malformed responses are
            # recovered by rebuilding both connections.
            self._diagnostics.action_result_unknown(
                self._connection,
                action,
                actual_snapshot,
                error,
            )
            return ActionOutcome(ActionExecution.UNKNOWN, error)

        try:
            self._check_rpc_session(self._session_id)
        except BridgeClientError as error:
            # The response arrived but the follow-up session check failed:
            # the operation result is known to be ambiguous, never resend.
            self._diagnostics.action_result_unknown(
                self._connection,
                action,
                actual_snapshot,
                error,
            )
            return ActionOutcome(ActionExecution.UNKNOWN, error)

        self._diagnostics.action_succeeded(self._connection, action, actual_snapshot)
        return ActionOutcome(ActionExecution.DISPATCHED)

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

    def _check_rpc_session(self, expected: int | None = None) -> int:
        changed = self._rpc.session_change
        if changed is not None:
            raise BridgeReconnectRequiredError(
                f"Bridge RPC session changed from {changed[0]} to {changed[1]}"
            )
        actual = self._rpc.session_id
        if actual == 0:
            raise BridgeProtocolError("Bridge returned an invalid zero session ID")
        if expected is not None and actual != expected:
            raise BridgeReconnectRequiredError(
                f"Bridge RPC session changed from {expected} to {actual}"
            )
        return actual

    def _require_baseline(self) -> LiveSplitSnapshot:
        baseline = self._baseline
        if baseline is None:
            raise RuntimeError("initial synchronization must complete first")
        return baseline

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._rpc.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
