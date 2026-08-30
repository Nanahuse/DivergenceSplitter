"""Runtime boundary for the official LiveSplit.Bridge client."""

from collections.abc import Callable
from typing import Protocol, Self

from divergencesplitter import Action, LiveSplitConnection
from livesplit_bridge import (
    BridgeClient,
    BridgeClientError,
    BridgeEventSubscriber,
    BridgeRemoteError,
    common_pb2,
)

from divergencesplitter_runtime.livesplit.mapping import (
    snapshot_from_proto,
    update_from_proto,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
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


class LiveSplitBridgeAdapter:
    def __init__(
        self,
        connection: LiveSplitConnection,
        *,
        diagnostics: LiveSplitBridgeDiagnostics,
        client: BridgeClient | None = None,
        subscriber: BridgeEventSubscriber | None = None,
        rpc_timeout_ms: int = 3000,
        event_timeout_ms: int | None = None,
    ) -> None:
        self._diagnostics = diagnostics
        owns_client = client is None
        self._client = (
            client
            if client is not None
            else BridgeClient(connection.rpc_endpoint, timeout_ms=rpc_timeout_ms)
        )
        try:
            self._subscriber = (
                subscriber
                if subscriber is not None
                else BridgeEventSubscriber(
                    connection.event_endpoint,
                    timeout_ms=event_timeout_ms,
                )
            )
        except Exception:
            if owns_client:
                self._client.close()
            raise
        self._closed = False

    def snapshot(self) -> LiveSplitSnapshot:
        return snapshot_from_proto(self._client.snapshot())

    def receive(self, *, timeout_ms: int | None = None) -> LiveSplitUpdate:
        return update_from_proto(self._subscriber.receive(timeout_ms=timeout_ms))

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
        try:
            self._subscriber.close()
        finally:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
