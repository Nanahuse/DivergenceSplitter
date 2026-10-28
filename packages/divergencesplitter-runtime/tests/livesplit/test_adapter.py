from __future__ import annotations

import unittest
from types import SimpleNamespace
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
    BridgeEvent,
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeRpcClient,
    EventType,
    RunState,
    SegmentInfo,
    TimerState,
    TimeValue,
)
from livesplit_bridge import (
    TimerPhase as BridgeTimerPhase,
)

_UINT32_MAX = 2**32 - 1


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
        self.timer_state = timer_state()
        self.run = run_state()
        self.calls: list[str] = []
        self.operation_error: Exception | None = None
        self.closed = False

    def get_timer_state(self) -> TimerState:
        self.calls.append("get_timer_state")
        return self.timer_state

    def get_run(self) -> RunState:
        self.calls.append("get_run")
        return self.run

    def _operation(self, name: str) -> None:
        self.calls.append(name)
        if self.operation_error is not None:
            raise self.operation_error

    def start(self) -> None:
        self._operation("start")

    def split(self) -> None:
        self._operation("split")

    def skip(self) -> None:
        self._operation("skip")

    def undo(self) -> None:
        self._operation("undo")

    def reset(self) -> None:
        self._operation("reset")

    def pause(self) -> None:
        self._operation("pause")

    def resume(self) -> None:
        self._operation("resume")

    def close(self) -> None:
        self.closed = True


def time_value() -> TimeValue:
    return TimeValue(real_time_ticks=0, game_time_ticks=None)


def segment(index: int, name: str) -> SegmentInfo:
    return SegmentInfo(
        index=index,
        name=name,
        comparisons=[],
        best_segment_time=time_value(),
    )


def run_state(
    *segments: SegmentInfo,
    game_name: str = "Game",
    category_name: str = "Any%",
) -> RunState:
    return RunState(
        game_name=game_name,
        category_name=category_name,
        offset_ticks=0,
        file_path=None,
        layout_path=None,
        metadata=None,
        comparisons=[],
        segments=list(segments) if segments else [segment(0, "A")],
    )


def timer_state(
    phase: BridgeTimerPhase = BridgeTimerPhase.RUNNING,
    split_index: int = 0,
) -> TimerState:
    return TimerState(
        phase=phase,
        split_index=split_index,
        real_time_ticks=0,
        game_time_ticks=None,
        is_game_time_initialized=False,
        is_game_time_paused=False,
    )


def event(
    kind: EventType,
    sequence: int,
    *,
    state: TimerState | None = None,
    session_id: int = 1,
) -> BridgeEvent:
    return BridgeEvent.model_validate(
        {
            "session_id": session_id,
            "event_sequence": sequence,
            "type": kind,
            "timer_state": state,
        }
    )


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

    def test_uses_protocol_v4_websocket_endpoints(self) -> None:
        self.assertEqual(
            rpc_endpoint(self.connection), "ws://127.0.0.1:54100/bridge/v4/rpc"
        )
        self.assertEqual(
            event_endpoint(self.connection), "ws://127.0.0.1:54100/bridge/v4/events"
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
            event(EventType.TIMER_SPLIT, 10, state=timer_state(split_index=0))
        )
        assert isinstance(first, LiveSplitUpdate)
        self.assertEqual(first.kind, LiveSplitUpdateKind.TRANSITION)
        # A timer transition remains observable even if phase and index do not change.
        update = self.adapter.handle_event(
            event(EventType.TIMER_SPLIT, 11, state=timer_state(split_index=0))
        )
        assert isinstance(update, LiveSplitUpdate)
        self.assertEqual(update.kind, LiveSplitUpdateKind.TRANSITION)
        self.assertEqual(update.state_epoch, 3)
        self.assertIs(
            self.adapter.handle_event(
                event(
                    EventType.TIMER_SPLIT,
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
            event(EventType.TIMER_STARTED, 3, state=timer_state())
        )
        result = self.adapter.handle_event(
            event(EventType.TIMER_SPLIT, 5, state=timer_state(split_index=0))
        )
        self.assertIs(result, LiveSplitResyncReason.GAP)
        self.assertEqual(self.diagnostics.gaps, [(1, 5)])
        current = self.adapter.current_snapshot
        assert current is not None
        self.assertEqual(current.split_index, 0)

    def test_duplicate_and_out_of_order_sequences_are_integrity_losses(self) -> None:
        self.sync()
        self.adapter.handle_event(
            event(EventType.TIMER_SPLIT, 4, state=timer_state(split_index=0))
        )

        self.assertIs(
            self.adapter.handle_event(
                event(EventType.TIMER_SPLIT, 4, state=timer_state(split_index=0))
            ),
            LiveSplitResyncReason.GAP,
        )
        self.assertEqual(self.diagnostics.gaps, [(1, 4)])
        self.assertIs(
            self.adapter.handle_event(
                event(EventType.TIMER_SPLIT, 3, state=timer_state(split_index=0))
            ),
            LiveSplitResyncReason.GAP,
        )
        self.assertEqual(self.diagnostics.gaps, [(1, 4), (1, 3)])
        self.assertEqual(self.adapter.event_sequence, 4)

    def test_sequence_wraps_from_uint32_max_to_one(self) -> None:
        self.sync()
        last = self.adapter.handle_event(
            event(EventType.TIMER_SPLIT, _UINT32_MAX, state=timer_state())
        )
        assert isinstance(last, LiveSplitUpdate)
        wrapped = self.adapter.handle_event(
            event(EventType.TIMER_SPLIT, 1, state=timer_state())
        )
        assert isinstance(wrapped, LiveSplitUpdate)
        self.assertEqual(wrapped.event_sequence, 1)
        self.assertEqual(self.adapter.event_sequence, 1)

    def test_reset_event_without_timer_state_queries_the_authoritative_state(
        self,
    ) -> None:
        self.sync()
        self.rpc.timer_state = timer_state(BridgeTimerPhase.NOT_RUNNING, -1)
        before = self.rpc.calls.count("get_timer_state")

        update = self.adapter.handle_event(event(EventType.TIMER_RESET, 1))

        self.assertEqual(self.rpc.calls.count("get_timer_state"), before + 1)
        assert isinstance(update, LiveSplitUpdate)
        self.assertEqual(update.snapshot.phase, TimerPhase.NOT_RUNNING)
        self.assertEqual(update.snapshot.split_index, -1)

    def test_other_timer_event_without_timer_state_is_a_protocol_error(self) -> None:
        self.sync()
        malformed = cast(
            BridgeEvent,
            SimpleNamespace(
                session_id=1,
                event_sequence=1,
                type=EventType.TIMER_SPLIT,
                timer_state=None,
            ),
        )
        with self.assertRaises(BridgeProtocolError):
            self.adapter.handle_event(malformed)

    def test_run_changed_fetches_run_and_only_marks_structure_changes(self) -> None:
        self.sync()
        epoch = self.adapter.state_epoch
        self.rpc.run = run_state()
        timing_update = self.adapter.handle_event(event(EventType.RUN_CHANGED, 1))
        assert isinstance(timing_update, LiveSplitUpdate)
        self.assertFalse(timing_update.run_structure_changed)
        self.assertEqual(timing_update.state_epoch, epoch)
        self.assertEqual(self.rpc.calls.count("get_timer_state"), 1)

        self.rpc.run = run_state(segment(0, "Changed"))
        structural_update = self.adapter.handle_event(event(EventType.RUN_CHANGED, 2))
        assert isinstance(structural_update, LiveSplitUpdate)
        self.assertTrue(structural_update.run_structure_changed)
        self.assertEqual(structural_update.state_epoch, epoch + 1)

    def test_context_changed_only_advances_the_sequence(self) -> None:
        self.sync()
        epoch = self.adapter.state_epoch

        update = self.adapter.handle_event(event(EventType.CONTEXT_CHANGED, 1))

        self.assertIsNone(update)
        self.assertEqual(self.adapter.event_sequence, 1)
        self.assertEqual(self.adapter.state_epoch, epoch)
        self.assertEqual(self.rpc.calls, ["get_timer_state", "get_run"])

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
        self.rpc.operation_error = BridgeRemoteError("operation_failed", "not allowed")
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
        self.rpc.operation_error = BridgeRemoteError("operation_failed", "not allowed")
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


if __name__ == "__main__":
    unittest.main()
