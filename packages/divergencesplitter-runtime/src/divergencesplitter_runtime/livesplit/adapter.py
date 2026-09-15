"""Runtime boundary for the official LiveSplit.Bridge client.

This adapter owns only the RPC side of the connection. Raw SUB event reception
is performed by :mod:`divergencesplitter_runtime.livesplit.event_receiver` on a
dedicated thread; :meth:`LiveSplitBridgeAdapter.handle_event` applies the
baseline/session/sequence validation to one received event.
"""

from collections.abc import Callable
from typing import Protocol, Self

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import (
    BridgeClientError,
    BridgeConnectionLostError,
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeRpcClient,
    common_pb2,
)

from divergencesplitter_runtime.livesplit.mapping import (
    run_info_from_proto,
    snapshot_from_proto,
    update_from_proto,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitRunInfo,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)


class LiveSplitBridgeDiagnostics(Protocol):
    """Receives Bridge operation facts without raising exceptions to the caller."""

    def snapshot_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        error: Exception,
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
                connection.rpc_endpoint,
                response_timeout_ms=rpc_timeout_ms,
            )
        )
        self._closed = False
        self._baseline: LiveSplitSnapshot | None = None
        self._run_info: LiveSplitRunInfo | None = None

    def attach(self) -> LiveSplitUpdate:
        response = self._rpc.attach()
        snapshot = snapshot_from_proto(response.snapshot)
        if response.session_id != snapshot.session_id:
            raise ValueError(
                "Bridge attach response and snapshot session IDs do not match"
            )
        run_info = self._sync_run(snapshot, force=True)
        self._set_baseline(snapshot)
        return LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot, run_info)

    def snapshot(self) -> LiveSplitSnapshot:
        return snapshot_from_proto(self._rpc.snapshot())

    def handle_event(
        self,
        event: common_pb2.BridgeEvent,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        """Validate one raw event against the baseline and convert it."""
        baseline = self._baseline
        if baseline is None:
            raise RuntimeError("attach must complete before receiving Bridge events")

        if event.type == common_pb2.EVENT_HEARTBEAT:
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
        if event.event_sequence > baseline.event_sequence + 1:
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.GAP
        if event.event_sequence <= baseline.event_sequence:
            return None
        if event.type == common_pb2.EVENT_HEARTBEAT:
            self._diagnostics.gap_detected(
                self._connection,
                baseline,
                event.session_id,
                event.event_sequence,
            )
            return LiveSplitResyncReason.GAP

        update = update_from_proto(event)
        run_info = self._sync_run(update.snapshot, force=False)
        self._set_baseline(update.snapshot)
        if run_info is None:
            return update
        return LiveSplitUpdate(update.kind, update.snapshot, run_info)

    def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
        previous = self._require_baseline()
        self._diagnostics.resync_started(self._connection, reason)
        snapshot = snapshot_from_proto(self._rpc.snapshot())
        if snapshot.session_id != previous.session_id:
            raise BridgeConnectionLostError("Bridge session changed during resync")
        run_info = self._sync_run(snapshot, force=True)
        self._set_baseline(snapshot)
        self._diagnostics.resync_completed(
            self._connection,
            reason,
            previous,
            snapshot,
        )
        return LiveSplitUpdate(LiveSplitUpdateKind.RESYNC, snapshot, run_info)

    def _sync_run(
        self,
        snapshot: LiveSplitSnapshot,
        *,
        force: bool,
    ) -> LiveSplitRunInfo | None:
        cached = self._run_info
        if (
            not force
            and cached is not None
            and snapshot.run_revision <= cached.run_revision
        ):
            return None
        run = run_info_from_proto(self._rpc.get_run())
        if run.session_id != snapshot.session_id:
            raise ValueError(
                "Bridge TimerSnapshot and RunSnapshot session IDs do not match"
            )
        if run.run_revision < snapshot.run_revision:
            raise ValueError(
                "Bridge RunSnapshot revision regressed behind TimerSnapshot"
            )
        self._run_info = run
        return run

    def _require_baseline(self) -> LiveSplitSnapshot:
        baseline = self._baseline
        if baseline is None:
            raise RuntimeError("attach must complete before Bridge resynchronization")
        return baseline

    def _set_baseline(self, snapshot: LiveSplitSnapshot) -> None:
        self._baseline = snapshot

    def execute_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
    ) -> None:
        actual_snapshot = self._require_baseline()

        if not self._matches_expected_state(expected_snapshot, actual_snapshot):
            self._diagnostics.snapshot_mismatched(
                self._connection,
                action,
                expected_snapshot,
                actual_snapshot,
            )
            return
        if not self._meets_action_precondition(action, actual_snapshot):
            self._diagnostics.action_precondition_failed(
                self._connection, action, actual_snapshot
            )
            return

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
            return
        except BridgeClientError as error:
            self._diagnostics.action_result_unknown(
                self._connection, action, actual_snapshot, error
            )
            raise

        if not response.success:
            self._diagnostics.action_rejected(
                self._connection,
                action,
                actual_snapshot,
                None,
                response.message,
            )
            return
        if not response.HasField("snapshot"):
            raise BridgeProtocolError(
                "successful timer operation response did not contain a snapshot"
            )
        result_snapshot = snapshot_from_proto(response.snapshot)
        self._diagnostics.action_succeeded(self._connection, action, result_snapshot)

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
