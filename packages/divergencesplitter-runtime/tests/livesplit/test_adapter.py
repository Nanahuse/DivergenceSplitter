from __future__ import annotations

import unittest
from typing import cast

from divergencesplitter import Action, LiveSplitConnection
from divergencesplitter_runtime.livesplit.adapter import (
    ActionExecution,
    LiveSplitBridgeAdapter,
    LiveSplitBridgeDiagnostics,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
    event_endpoint,
    rpc_endpoint,
)
from livesplit_bridge import (
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeRpcClient,
    common_pb2,
    run_pb2,
)


class Diagnostics:
    def __init__(self) -> None:
        self.gaps: list[tuple[int, int]] = []
        self.dispatches: list[str] = []
        self.successes: list[str] = []
        self.rejections: list[str] = []

    def snapshot_mismatched(self, *_: object) -> None: ...

    def action_precondition_failed(self, *_: object) -> None: ...

    def action_dispatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        session_id: int | None,
        event_sequence: int | None,
        state_epoch: int,
    ) -> None:
        self.dispatches.append(action.operation)

    def action_succeeded(
        self, _connection: object, action: Action, _snapshot: object
    ) -> None:
        self.successes.append(action.operation)

    def action_rejected(self, _connection: object, action: Action, *_: object) -> None:
        self.rejections.append(action.operation)

    def action_result_unknown(self, *_: object) -> None: ...

    def gap_detected(
        self,
        _connection: object,
        _baseline: object,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None:
        self.gaps.append((received_session_id, received_event_sequence))


class FakeRpc:
    def __init__(self) -> None:
        self.session_id = 1
        self.session_change: tuple[int, int] | None = None
        self.timer_state = common_pb2.TimerState(
            phase=common_pb2.RUNNING,
            split_index=0,
        )
        self.run = run_pb2.RunState(
            game_name="Game",
            category_name="Any%",
            segments=(run_pb2.SegmentInfo(index=0, name="A"),),
        )
        self.calls: list[str] = []
        self.operation_error: Exception | None = None
        self.closed = False

    def get_timer_state(self) -> common_pb2.TimerState:
        self.calls.append("get_timer_state")
        return self.timer_state

    def get_run(self) -> run_pb2.RunState:
        self.calls.append("get_run")
        return self.run

    def _operation(self, name: str) -> common_pb2.OperationResponse:
        self.calls.append(name)
        if self.operation_error is not None:
            raise self.operation_error
        return common_pb2.OperationResponse()

    def start(self) -> common_pb2.OperationResponse:
        return self._operation("start")

    def split(self) -> common_pb2.OperationResponse:
        return self._operation("split")

    def skip(self) -> common_pb2.OperationResponse:
        return self._operation("skip")

    def undo(self) -> common_pb2.OperationResponse:
        return self._operation("undo")

    def reset(self) -> common_pb2.OperationResponse:
        return self._operation("reset")

    def pause(self) -> common_pb2.OperationResponse:
        return self._operation("pause")

    def resume(self) -> common_pb2.OperationResponse:
        return self._operation("resume")

    def close(self) -> None:
        self.closed = True


def timer_state(
    phase: common_pb2.TimerPhase = common_pb2.RUNNING,
    split_index: int = 0,
) -> common_pb2.TimerState:
    return common_pb2.TimerState(phase=phase, split_index=split_index)


def event(
    kind: common_pb2.BridgeEventType,
    sequence: int,
    *,
    state: common_pb2.TimerState | None = None,
    session_id: int = 1,
) -> common_pb2.BridgeEvent:
    value = common_pb2.BridgeEvent(
        type=kind,
        session_id=session_id,
        event_sequence=sequence,
    )
    if state is not None:
        value.timer_state.CopyFrom(state)
    return value


class LiveSplitBridgeAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = LiveSplitConnection(54100)
        self.diagnostics = Diagnostics()
        self.rpc = FakeRpc()
        self.adapter = LiveSplitBridgeAdapter(
            self.connection,
            diagnostics=cast(LiveSplitBridgeDiagnostics, self.diagnostics),
            rpc=cast(BridgeRpcClient, self.rpc),
        )

    def tearDown(self) -> None:
        self.adapter.close()

    def sync(self) -> None:
        self.adapter.synchronize()

    def test_uses_protocol_v3_websocket_endpoints(self) -> None:
        self.assertEqual(
            rpc_endpoint(self.connection), "ws://127.0.0.1:54100/bridge/v3/rpc"
        )
        self.assertEqual(
            event_endpoint(self.connection), "ws://127.0.0.1:54100/bridge/v3/events"
        )

    def test_initial_sync_uses_only_timer_and_run_queries(self) -> None:
        update = self.adapter.synchronize()

        self.assertEqual(self.rpc.calls, ["get_timer_state", "get_run"])
        self.assertEqual(update.kind, LiveSplitUpdateKind.INITIAL)
        self.assertEqual(update.session_id, 1)
        self.assertEqual(update.state_epoch, 1)
        self.assertEqual(update.snapshot.phase, TimerPhase.RUNNING)
        self.assertEqual(update.snapshot.split_count, 1)
        self.assertIsNotNone(update.run_info)
        assert update.run_info is not None
        self.assertEqual(update.run_info.game_name, "Game")

    def test_event_order_and_session_validation(self) -> None:
        self.sync()
        first = self.adapter.handle_event(
            event(common_pb2.EVENT_TIMER_SPLIT, 10, state=timer_state(split_index=0))
        )
        assert isinstance(first, LiveSplitUpdate)
        self.assertEqual(first.kind, LiveSplitUpdateKind.TRANSITION)
        # A timer transition remains observable even if phase and index do not change.
        update = self.adapter.handle_event(
            event(common_pb2.EVENT_TIMER_SPLIT, 11, state=timer_state(split_index=0))
        )
        assert isinstance(update, LiveSplitUpdate)
        self.assertEqual(update.kind, LiveSplitUpdateKind.TRANSITION)
        self.assertEqual(update.state_epoch, 3)
        self.assertEqual(
            self.adapter.handle_event(
                event(
                    common_pb2.EVENT_TIMER_SPLIT, 11, state=timer_state(split_index=0)
                )
            ),
            None,
        )
        self.assertIs(
            self.adapter.handle_event(
                event(
                    common_pb2.EVENT_TIMER_SPLIT,
                    12,
                    session_id=2,
                    state=timer_state(split_index=0),
                )
            ),
            LiveSplitResyncReason.SESSION_CHANGED,
        )

    def test_sequence_gap_requires_resync_and_does_not_infer_missing_events(
        self,
    ) -> None:
        self.sync()
        self.adapter.handle_event(
            event(common_pb2.EVENT_TIMER_STARTED, 3, state=timer_state())
        )
        result = self.adapter.handle_event(
            event(common_pb2.EVENT_TIMER_SPLIT, 5, state=timer_state(split_index=0))
        )
        self.assertIs(result, LiveSplitResyncReason.GAP)
        self.assertEqual(self.diagnostics.gaps, [(1, 5)])
        current = self.adapter.current_snapshot
        assert current is not None
        self.assertEqual(current.split_index, 0)

    def test_reset_event_without_timer_state_queries_the_authoritative_state(
        self,
    ) -> None:
        self.sync()
        self.rpc.timer_state = timer_state(common_pb2.NOT_RUNNING, -1)
        before = self.rpc.calls.count("get_timer_state")

        update = self.adapter.handle_event(event(common_pb2.EVENT_TIMER_RESET, 1))

        self.assertEqual(self.rpc.calls.count("get_timer_state"), before + 1)
        assert isinstance(update, LiveSplitUpdate)
        self.assertEqual(update.snapshot.phase, TimerPhase.NOT_RUNNING)
        self.assertEqual(update.snapshot.split_index, -1)

    def test_run_changed_fetches_run_and_only_marks_structure_changes(self) -> None:
        self.sync()
        epoch = self.adapter.state_epoch
        self.rpc.run = run_pb2.RunState(
            game_name="Game",
            category_name="Any%",
            segments=(run_pb2.SegmentInfo(index=0, name="A"),),
        )
        timing_update = self.adapter.handle_event(
            event(common_pb2.EVENT_RUN_CHANGED, 1)
        )
        assert isinstance(timing_update, LiveSplitUpdate)
        self.assertFalse(timing_update.run_structure_changed)
        self.assertEqual(timing_update.state_epoch, epoch)
        self.assertEqual(self.rpc.calls.count("get_timer_state"), 1)

        self.rpc.run = run_pb2.RunState(
            game_name="Game",
            category_name="Any%",
            segments=(run_pb2.SegmentInfo(index=0, name="Changed"),),
        )
        structural_update = self.adapter.handle_event(
            event(common_pb2.EVENT_RUN_CHANGED, 2)
        )
        assert isinstance(structural_update, LiveSplitUpdate)
        self.assertTrue(structural_update.run_structure_changed)
        self.assertEqual(structural_update.state_epoch, epoch + 1)

    def test_control_success_has_no_state_query_or_optimistic_transition(self) -> None:
        self.sync()
        baseline = self.adapter.current_snapshot
        assert baseline is not None
        epoch = self.adapter.state_epoch
        query_count = self.rpc.calls.count("get_timer_state")

        outcome = self.adapter.execute_action(Action("split"), baseline, epoch)

        self.assertEqual(outcome.execution, ActionExecution.DISPATCHED)
        self.assertEqual(self.rpc.calls[-1], "split")
        self.assertEqual(self.rpc.calls.count("get_timer_state"), query_count)
        self.assertEqual(self.diagnostics.dispatches, ["split"])
        self.assertEqual(self.adapter.current_snapshot, baseline)
        self.assertEqual(self.adapter.state_epoch, epoch)

    def test_stale_epoch_is_not_dispatched(self) -> None:
        self.sync()
        baseline = self.adapter.current_snapshot
        assert baseline is not None
        outcome = self.adapter.execute_action(
            Action("split"), baseline, self.adapter.state_epoch - 1
        )
        self.assertEqual(outcome.execution, ActionExecution.NOT_DISPATCHED)
        self.assertNotIn("split", self.rpc.calls)

    def test_remote_rejection_is_distinct_from_unknown_outcome(self) -> None:
        self.sync()
        self.rpc.operation_error = BridgeRemoteError(4, "not allowed")
        baseline = self.adapter.current_snapshot
        assert baseline is not None
        outcome = self.adapter.execute_action(
            Action("split"), baseline, self.adapter.state_epoch
        )
        self.assertEqual(outcome.execution, ActionExecution.REJECTED)
        self.assertEqual(self.diagnostics.rejections, ["split"])
        self.assertNotIn("get_timer_state", self.rpc.calls[2:])

    def test_remote_error_with_session_change_is_not_a_rejection(self) -> None:
        self.sync()
        self.rpc.operation_error = BridgeRemoteError(4, "not allowed")
        # The client commits the new session even for a RemoteError.
        self.rpc.session_change = (1, 2)
        baseline = self.adapter.current_snapshot
        assert baseline is not None
        outcome = self.adapter.execute_action(
            Action("split"), baseline, self.adapter.state_epoch
        )
        self.assertEqual(outcome.execution, ActionExecution.UNKNOWN)
        self.assertEqual(self.diagnostics.rejections, [])

    def test_protocol_error_after_control_is_unknown_and_not_resent(self) -> None:
        self.sync()
        self.rpc.operation_error = BridgeProtocolError("malformed response")
        baseline = self.adapter.current_snapshot
        assert baseline is not None
        before = list(self.rpc.calls)
        outcome = self.adapter.execute_action(
            Action("split"), baseline, self.adapter.state_epoch
        )
        self.assertEqual(outcome.execution, ActionExecution.UNKNOWN)
        # Only the single control request was sent; nothing is retried.
        self.assertEqual(self.rpc.calls, before + ["split"])

    def test_protocol_version_mismatch_is_fatal(self) -> None:
        self.sync()
        self.rpc.operation_error = BridgeProtocolError(
            "Protocol version mismatch: expected 3, got 2"
        )
        baseline = self.adapter.current_snapshot
        assert baseline is not None
        outcome = self.adapter.execute_action(
            Action("split"), baseline, self.adapter.state_epoch
        )
        self.assertEqual(outcome.execution, ActionExecution.FAILED)
        self.assertIsNotNone(outcome.error)


if __name__ == "__main__":
    unittest.main()
