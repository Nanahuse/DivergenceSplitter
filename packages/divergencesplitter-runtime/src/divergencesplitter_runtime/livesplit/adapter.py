"""Runtime boundary for the official LiveSplit.Bridge client."""

from collections.abc import Callable
from typing import Protocol, Self

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import (
    BridgeClient,
    BridgeClientError,
    BridgeRemoteError,
    common_pb2,
)

from divergencesplitter_runtime.livesplit.mapping import (
    snapshot_from_proto,
    update_from_proto,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)


class LiveSplitBridgeDiagnostics(Protocol):
    """Receives Bridge operation facts without raising exceptions to the caller."""

    def snapshot_failed(self, action: Action, error: Exception) -> None: ...

    def snapshot_mismatched(
        self,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None: ...

    def action_precondition_failed(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_succeeded(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_rejected(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None: ...

    def action_result_unknown(
        self,
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
        client: BridgeClient | None = None,
        rpc_timeout_ms: int = 3000,
        heartbeat_timeout_ms: int = 3000,
    ) -> None:
        self._connection = connection
        self._diagnostics = diagnostics
        self._client = (
            client
            if client is not None
            else BridgeClient(
                connection.rpc_endpoint,
                connection.event_endpoint,
                response_timeout_ms=rpc_timeout_ms,
                heartbeat_timeout_ms=heartbeat_timeout_ms,
            )
        )
        self._closed = False
        self._baseline: LiveSplitSnapshot | None = None

    def attach(self) -> LiveSplitUpdate:
        response = self._client.attach()
        snapshot = snapshot_from_proto(response.snapshot)
        if response.session_id != snapshot.session_id:
            raise ValueError(
                "Bridge attach response and snapshot session IDs do not match"
            )
        self._set_baseline(snapshot)
        return LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot)

    def snapshot(self) -> LiveSplitSnapshot:
        return snapshot_from_proto(self._client.snapshot())

    def receive(
        self,
        *,
        timeout_ms: int | None = None,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        event = self._client.receive(timeout_ms=timeout_ms)
        if event is None:
            return None

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
        self._set_baseline(update.snapshot)
        return update

    def reconnect(self) -> LiveSplitUpdate:
        return self._resync(LiveSplitResyncReason.CONNECTION_LOST, reconnect=True)

    def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
        return self._resync(reason, reconnect=False)

    def _resync(
        self,
        reason: LiveSplitResyncReason,
        *,
        reconnect: bool,
    ) -> LiveSplitUpdate:
        previous = self._require_baseline()
        self._diagnostics.resync_started(self._connection, reason)
        proto_snapshot = (
            self._client.reconnect() if reconnect else self._client.snapshot()
        )
        snapshot = snapshot_from_proto(proto_snapshot)
        self._set_baseline(snapshot)
        self._diagnostics.resync_completed(
            self._connection,
            reason,
            previous,
            snapshot,
        )
        return LiveSplitUpdate(LiveSplitUpdateKind.RESYNC, snapshot)

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
        try:
            actual_snapshot = self.snapshot()
        except Exception as error:  # noqa: BLE001
            self._diagnostics.snapshot_failed(action, error)
            return

        if not self._matches_expected_state(expected_snapshot, actual_snapshot):
            self._diagnostics.snapshot_mismatched(
                action,
                expected_snapshot,
                actual_snapshot,
            )
            return
        if not self._meets_action_precondition(action, actual_snapshot):
            self._diagnostics.action_precondition_failed(action, actual_snapshot)
            return

        operation: Callable[[], common_pb2.OperationResponse] = {
            "split": self._client.split,
            "skip": self._client.skip,
            "undo": self._client.undo,
            "reset": self._client.reset,
            "pause": self._client.pause,
            "resume": self._client.resume,
        }[action.operation]
        try:
            response = operation()
        except BridgeRemoteError as error:
            self._diagnostics.action_rejected(
                action,
                actual_snapshot,
                error.code,
                error.message,
            )
            return
        except BridgeClientError as error:
            self._diagnostics.action_result_unknown(action, actual_snapshot, error)
            return

        if not response.success:
            self._diagnostics.action_rejected(
                action,
                actual_snapshot,
                None,
                response.message,
            )
            return
        self._diagnostics.action_succeeded(action, actual_snapshot)

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
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
