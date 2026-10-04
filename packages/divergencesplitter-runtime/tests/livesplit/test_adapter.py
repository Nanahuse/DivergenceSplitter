import unittest
from typing import Any
from unittest.mock import create_autospec, patch

from divergencesplitter import Action, LiveSplitConnection
from divergencesplitter_runtime import (
    ActionExecution,
    LiveSplitBridgeAdapter,
    LiveSplitBridgeDiagnostics,
    LiveSplitResyncReason,
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)
from divergencesplitter_runtime.livesplit import (
    event_update_kind,
    rpc_endpoint,
    run_info_from_proto,
    snapshot_from_timer_state,
)
from livesplit_bridge import (
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeResponseTimeoutError,
    BridgeRpcClient,
    bridge_pb2,
    common_pb2,
    run_pb2,
)


def proto_timer_state(
    *,
    session_id: int = 1,
    state_revision: int = 2,
    run_revision: int = 1,
    phase: common_pb2.TimerPhase = common_pb2.RUNNING,
    split_index: int = 0,
) -> common_pb2.TimerState:
    return common_pb2.TimerState(
        session_id=session_id,
        state_revision=state_revision,
        run_revision=run_revision,
        phase=phase,
        split_index=split_index,
    )


def proto_run(
    *,
    session_id: int = 1,
    run_revision: int = 1,
    segments: tuple[tuple[int, str], ...] = ((0, "A"), (1, "B")),
) -> run_pb2.RunState:
    return run_pb2.RunState(
        session_id=session_id,
        run_revision=run_revision,
        segments=[
            run_pb2.SegmentInfo(index=index, name=name) for index, name in segments
        ],
    )


def proto_event(
    event_type: common_pb2.BridgeEventType,
    *,
    timer_state: common_pb2.TimerState | None = None,
    session_id: int | None = None,
    event_sequence: int = 1,
) -> common_pb2.BridgeEvent:
    if timer_state is None:
        timer_state = proto_timer_state()
    if session_id is None:
        session_id = timer_state.session_id
    return common_pb2.BridgeEvent(
        session_id=session_id,
        event_sequence=event_sequence,
        type=event_type,
        timer_state=timer_state,
    )


def domain_snapshot(
    *,
    session_id: int = 1,
    state_revision: int = 2,
    run_revision: int = 1,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 2,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=session_id,
        state_revision=state_revision,
        run_revision=run_revision,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


def domain_run(
    *,
    session_id: int = 1,
    run_revision: int = 1,
    segments: tuple[tuple[int, str], ...] = ((0, "A"), (1, "B")),
) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=session_id,
        run_revision=run_revision,
        segments=tuple(
            LiveSplitSegmentInfo(index=index, name=name) for index, name in segments
        ),
    )


class RecordingDiagnostics(LiveSplitBridgeDiagnostics):
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.stream_events: list[tuple[object, ...]] = []

    def snapshot_mismatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None:
        self.events.append(
            ("snapshot_mismatched", connection, action, expected, actual)
        )

    def action_precondition_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self.events.append(("action_precondition_failed", connection, action, snapshot))

    def action_succeeded(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self.events.append(("action_succeeded", connection, action, snapshot))

    def action_rejected(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None:
        self.events.append(
            ("action_rejected", connection, action, snapshot, code, message)
        )

    def action_result_unknown(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None:
        self.events.append(
            ("action_result_unknown", connection, action, snapshot, error)
        )

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None:
        self.stream_events.append(
            (
                "gap_detected",
                connection,
                baseline,
                received_session_id,
                received_event_sequence,
            )
        )

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None:
        self.stream_events.append(
            ("heartbeat_received", connection, session_id, event_sequence)
        )

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None:
        self.stream_events.append(("resync_started", connection, reason))

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        self.stream_events.append(
            ("resync_completed", connection, reason, previous, current)
        )


class MappingTest(unittest.TestCase):
    def test_snapshot_maps_supported_phases(self) -> None:
        cases = (
            (common_pb2.NOT_RUNNING, -1, TimerPhase.NOT_RUNNING),
            (common_pb2.STARTING, 0, TimerPhase.STARTING),
            (common_pb2.RUNNING, 0, TimerPhase.RUNNING),
            (common_pb2.PAUSED, 0, TimerPhase.PAUSED),
            (common_pb2.ENDED, 2, TimerPhase.ENDED),
        )
        for proto_phase, split_index, expected in cases:
            with self.subTest(proto_phase=proto_phase):
                actual = snapshot_from_timer_state(
                    proto_timer_state(
                        phase=proto_phase,
                        split_index=split_index,
                    ),
                    split_count=2,
                )
                self.assertEqual(actual.phase, expected)
                self.assertEqual(actual.session_id, 1)
                self.assertEqual(actual.state_revision, 2)
                self.assertEqual(actual.run_revision, 1)
                self.assertEqual(actual.split_count, 2)

    def test_snapshot_preserves_run_revision(self) -> None:
        actual = snapshot_from_timer_state(
            proto_timer_state(run_revision=7), split_count=2
        )

        self.assertEqual(actual.run_revision, 7)

    def test_run_info_maps_segments(self) -> None:
        actual = run_info_from_proto(
            proto_run(
                session_id=10,
                run_revision=20,
                segments=((0, "A"), (1, "B")),
            )
        )

        self.assertEqual(
            actual,
            LiveSplitRunInfo(
                session_id=10,
                run_revision=20,
                segments=(
                    LiveSplitSegmentInfo(0, "A"),
                    LiveSplitSegmentInfo(1, "B"),
                ),
            ),
        )

    def test_snapshot_rejects_unsupported_phases(self) -> None:
        for phase in (common_pb2.TIMER_PHASE_UNSPECIFIED,):
            with (
                self.subTest(phase=phase),
                self.assertRaisesRegex(ValueError, "unsupported timer phase"),
            ):
                snapshot_from_timer_state(proto_timer_state(phase=phase), split_count=2)

    def test_timer_and_run_events_are_transitions(self) -> None:
        event_types = (
            common_pb2.EVENT_TIMER_STARTED,
            common_pb2.EVENT_TIMER_SPLIT,
            common_pb2.EVENT_TIMER_SKIPPED,
            common_pb2.EVENT_TIMER_UNDO,
            common_pb2.EVENT_TIMER_RESET,
            common_pb2.EVENT_TIMER_PAUSED,
            common_pb2.EVENT_TIMER_RESUMED,
            common_pb2.EVENT_RUN_CHANGED,
        )
        for event_type in event_types:
            with self.subTest(event_type=event_type):
                self.assertIs(
                    event_update_kind(event_type), LiveSplitUpdateKind.TRANSITION
                )

    def test_game_time_events_are_periodic(self) -> None:
        event_types = (
            common_pb2.EVENT_GAME_TIME_INITIALIZED,
            common_pb2.EVENT_GAME_TIME_SET,
            common_pb2.EVENT_GAME_TIME_PAUSED,
            common_pb2.EVENT_GAME_TIME_RESUMED,
        )
        for event_type in event_types:
            with self.subTest(event_type=event_type):
                self.assertIs(
                    event_update_kind(event_type), LiveSplitUpdateKind.PERIODIC
                )

    def test_runtime_changed_event_has_no_scenario_update(self) -> None:
        self.assertIsNone(event_update_kind(common_pb2.EVENT_RUNTIME_CHANGED))

    def test_unspecified_event_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported Bridge event type"):
            event_update_kind(common_pb2.BRIDGE_EVENT_UNSPECIFIED)


class AdapterTest(unittest.TestCase):
    def make_attached_adapter(
        self,
        *,
        state_revision: int = 2,
        run_revision: int = 1,
        segments: tuple[tuple[int, str], ...] = ((0, "A"), (1, "B")),
        diagnostics: RecordingDiagnostics | None = None,
    ) -> tuple[LiveSplitBridgeAdapter, Any]:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            timer_state=proto_timer_state(
                state_revision=state_revision, run_revision=run_revision
            ),
        )
        client.get_run.return_value = proto_run(
            session_id=1, run_revision=run_revision, segments=segments
        )
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=diagnostics or RecordingDiagnostics(),
            rpc=client,
        )
        adapter.attach()
        return adapter, client

    def test_uses_connection_port_for_rpc_client(self) -> None:
        connection = LiveSplitConnection(54000)
        with patch(
            "divergencesplitter_runtime.livesplit.adapter.BridgeRpcClient",
            autospec=True,
        ) as client_type:
            adapter = LiveSplitBridgeAdapter(
                connection,
                diagnostics=RecordingDiagnostics(),
                rpc_timeout_ms=10,
            )
            adapter.close()

        client_type.assert_called_once_with(
            rpc_endpoint(connection),
            response_timeout_ms=10,
        )
        client_type.return_value.close.assert_called_once_with()

    def test_attach_establishes_initial_snapshot_and_run(self) -> None:
        adapter, client = self.make_attached_adapter()

        self.assertEqual(
            adapter._require_baseline(),
            domain_snapshot(state_revision=2, run_revision=1, split_count=2),
        )
        client.get_run.assert_called_once_with()
        adapter.close()
        client.close.assert_called_once_with()

    def test_runtime_changed_event_advances_cursor_without_update(self) -> None:
        adapter, client = self.make_attached_adapter()

        update = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_RUNTIME_CHANGED,
                timer_state=proto_timer_state(state_revision=2, run_revision=1),
                event_sequence=1,
            )
        )

        self.assertIsNone(update)
        client.get_run.assert_called_once_with()

    def test_sequence_must_be_contiguous(self) -> None:
        adapter, _ = self.make_attached_adapter()
        adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(state_revision=3, split_index=1),
                event_sequence=1,
            )
        )

        duplicate = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(state_revision=3, split_index=1),
                event_sequence=1,
            )
        )
        self.assertIsNone(duplicate)

        gap = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(state_revision=4, split_index=1),
                event_sequence=3,
            )
        )
        self.assertIs(gap, LiveSplitResyncReason.GAP)

    def test_session_change_requests_resync(self) -> None:
        adapter, _ = self.make_attached_adapter()

        reason = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(session_id=2, state_revision=3),
                event_sequence=1,
            )
        )

        self.assertIs(reason, LiveSplitResyncReason.SESSION_CHANGED)

    def test_heartbeat_semantics(self) -> None:
        adapter, _ = self.make_attached_adapter()
        adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(state_revision=3, split_index=1),
                event_sequence=4,
            )
        )

        self.assertIsNone(
            adapter.handle_event(
                proto_event(common_pb2.EVENT_HEARTBEAT, event_sequence=4)
            )
        )
        self.assertIsNone(
            adapter.handle_event(
                proto_event(common_pb2.EVENT_HEARTBEAT, event_sequence=2)
            )
        )
        self.assertIs(
            adapter.handle_event(
                proto_event(common_pb2.EVENT_HEARTBEAT, event_sequence=5)
            ),
            LiveSplitResyncReason.GAP,
        )

    def test_resync_fetches_authoritative_state(self) -> None:
        adapter, client = self.make_attached_adapter()
        client.get_timer_state.return_value = proto_timer_state(
            state_revision=9, run_revision=4
        )
        client.get_run.return_value = proto_run(
            session_id=1, run_revision=4, segments=((0, "A"), (1, "B"), (2, "C"))
        )

        update = adapter.resync(LiveSplitResyncReason.GAP)

        self.assertIs(update.kind, LiveSplitUpdateKind.RESYNC)
        self.assertEqual(update.snapshot.split_count, 3)
        self.assertEqual(
            update.run_info,
            domain_run(run_revision=4, segments=((0, "A"), (1, "B"), (2, "C"))),
        )

    def test_close_is_idempotent(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=RecordingDiagnostics(),
            rpc=client,
        )

        adapter.close()
        adapter.close()

        client.close.assert_called_once_with()


class RunSynchronizationTest(unittest.TestCase):
    def test_initial_attach_always_fetches_run(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            timer_state=proto_timer_state(state_revision=2, run_revision=1),
        )
        client.get_run.return_value = proto_run(session_id=1, run_revision=1)
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=RecordingDiagnostics(),
            rpc=client,
        )

        initial = adapter.attach()

        self.assertEqual(initial.run_info, domain_run())
        client.get_run.assert_called_once_with()

    def test_run_changed_event_fetches_run_by_revision(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            timer_state=proto_timer_state(state_revision=2, run_revision=1),
        )
        client.get_run.side_effect = (
            proto_run(session_id=1, run_revision=1),
            proto_run(session_id=1, run_revision=2, segments=((0, "A"),)),
        )
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=RecordingDiagnostics(),
            rpc=client,
        )
        adapter.attach()

        update = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_RUN_CHANGED,
                timer_state=proto_timer_state(state_revision=2, run_revision=2),
                event_sequence=1,
            )
        )

        assert isinstance(update, LiveSplitUpdate)
        self.assertEqual(
            update.run_info, domain_run(run_revision=2, segments=((0, "A"),))
        )
        self.assertEqual(update.snapshot.split_count, 1)
        self.assertEqual(client.get_run.call_count, 2)

    def test_unchanged_run_revision_skips_get_run(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            timer_state=proto_timer_state(state_revision=2, run_revision=1),
        )
        client.get_run.return_value = proto_run(session_id=1, run_revision=1)
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=RecordingDiagnostics(),
            rpc=client,
        )
        adapter.attach()

        update = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(state_revision=3, run_revision=1),
                event_sequence=1,
            )
        )

        assert isinstance(update, LiveSplitUpdate)
        self.assertIsNone(update.run_info)
        client.get_run.assert_called_once_with()

    def test_stale_run_snapshot_is_rejected(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            timer_state=proto_timer_state(state_revision=2, run_revision=1),
        )
        client.get_run.side_effect = (
            proto_run(session_id=1, run_revision=1),
            proto_run(session_id=1, run_revision=1),
        )
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=RecordingDiagnostics(),
            rpc=client,
        )
        adapter.attach()

        with self.assertRaisesRegex(ValueError, "revision regressed"):
            adapter.handle_event(
                proto_event(
                    common_pb2.EVENT_RUN_CHANGED,
                    timer_state=proto_timer_state(state_revision=2, run_revision=2),
                    event_sequence=1,
                )
            )


class ActionExecutionTest(unittest.TestCase):
    def make_adapter(
        self,
        client: BridgeRpcClient,
        diagnostics: LiveSplitBridgeDiagnostics,
        *,
        baseline: LiveSplitSnapshot | None = None,
    ) -> LiveSplitBridgeAdapter:
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection(54000),
            diagnostics=diagnostics,
            rpc=client,
        )
        adapter._baseline = baseline if baseline is not None else domain_snapshot()
        return adapter

    def assert_no_operation(self, client: BridgeRpcClient) -> None:
        for operation in (
            "start",
            "split",
            "skip",
            "undo",
            "reset",
            "pause",
            "resume",
        ):
            getattr(client, operation).assert_not_called()

    def test_maps_each_action_to_one_client_operation(self) -> None:
        cases = (
            ("start", common_pb2.NOT_RUNNING, -1),
            ("split", common_pb2.RUNNING, 0),
            ("skip", common_pb2.RUNNING, 0),
            ("undo", common_pb2.PAUSED, 1),
            ("reset", common_pb2.ENDED, 2),
            ("pause", common_pb2.RUNNING, 0),
            ("resume", common_pb2.PAUSED, 0),
        )
        for operation, phase, split_index in cases:
            with self.subTest(operation=operation):
                client = create_autospec(BridgeRpcClient, instance=True)
                client.get_run.return_value = proto_run(session_id=1, run_revision=1)
                baseline = domain_snapshot(
                    phase={
                        common_pb2.NOT_RUNNING: TimerPhase.NOT_RUNNING,
                        common_pb2.RUNNING: TimerPhase.RUNNING,
                        common_pb2.PAUSED: TimerPhase.PAUSED,
                        common_pb2.ENDED: TimerPhase.ENDED,
                    }[phase],
                    split_index=split_index,
                    split_count=2,
                )
                getattr(client, operation).return_value = common_pb2.OperationResponse(
                    success=True,
                    timer_state=proto_timer_state(
                        state_revision=3,
                        phase=phase,
                        split_index=split_index,
                    ),
                )
                diagnostics = RecordingDiagnostics()
                action = Action(operation=operation)
                adapter = self.make_adapter(client, diagnostics, baseline=baseline)

                outcome = adapter.execute_action(action, baseline)

                self.assertIs(outcome.execution, ActionExecution.DISPATCHED)
                self.assertIsNotNone(outcome.update)
                getattr(client, operation).assert_called_once_with()

    def test_rejects_actions_whose_phase_or_position_is_invalid(self) -> None:
        cases = (
            ("split", TimerPhase.PAUSED, 0),
            ("skip", TimerPhase.RUNNING, 1),
            ("undo", TimerPhase.RUNNING, 0),
            ("undo", TimerPhase.PAUSED, 0),
            ("reset", TimerPhase.NOT_RUNNING, -1),
            ("pause", TimerPhase.PAUSED, 0),
            ("resume", TimerPhase.RUNNING, 0),
        )
        for operation, phase, split_index in cases:
            with self.subTest(operation=operation, phase=phase):
                client = create_autospec(BridgeRpcClient, instance=True)
                diagnostics = RecordingDiagnostics()
                action = Action(operation=operation)
                snapshot = domain_snapshot(
                    phase=phase, split_index=split_index, split_count=2
                )

                outcome = self.make_adapter(
                    client, diagnostics, baseline=snapshot
                ).execute_action(action, snapshot)

                self.assertIs(outcome.execution, ActionExecution.NOT_DISPATCHED)
                self.assert_no_operation(client)
                self.assertEqual(
                    diagnostics.events,
                    [
                        (
                            "action_precondition_failed",
                            LiveSplitConnection(54000),
                            action,
                            snapshot,
                        )
                    ],
                )

    def test_expected_state_mismatch_does_not_operate(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")
        expected = domain_snapshot(state_revision=1)
        actual = domain_snapshot(state_revision=2)

        outcome = self.make_adapter(
            client, diagnostics, baseline=actual
        ).execute_action(action, expected)

        self.assertIs(outcome.execution, ActionExecution.NOT_DISPATCHED)
        self.assert_no_operation(client)
        self.assertEqual(
            diagnostics.events,
            [
                (
                    "snapshot_mismatched",
                    LiveSplitConnection(54000),
                    action,
                    expected,
                    actual,
                )
            ],
        )

    def test_success_applies_operation_response_state(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.get_run.return_value = proto_run(session_id=1, run_revision=1)
        client.split.return_value = common_pb2.OperationResponse(
            success=True,
            timer_state=proto_timer_state(state_revision=3, split_index=1),
        )
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")
        baseline = domain_snapshot(state_revision=2, split_index=0)
        adapter = self.make_adapter(client, diagnostics, baseline=baseline)

        outcome = adapter.execute_action(action, baseline)

        self.assertIs(outcome.execution, ActionExecution.DISPATCHED)
        assert outcome.update is not None
        self.assertIs(outcome.update.kind, LiveSplitUpdateKind.TRANSITION)
        self.assertEqual(outcome.update.snapshot.state_revision, 3)
        self.assertEqual(outcome.update.snapshot.split_index, 1)
        self.assertEqual(adapter._require_baseline(), outcome.update.snapshot)
        self.assertEqual(
            diagnostics.events,
            [
                (
                    "action_succeeded",
                    LiveSplitConnection(54000),
                    action,
                    outcome.update.snapshot,
                )
            ],
        )

    def test_matching_event_after_operation_is_not_reapplied(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.get_run.return_value = proto_run(session_id=1, run_revision=1)
        client.split.return_value = common_pb2.OperationResponse(
            success=True,
            timer_state=proto_timer_state(state_revision=3, split_index=1),
        )
        baseline = domain_snapshot(state_revision=2, split_index=0)
        adapter = self.make_adapter(client, RecordingDiagnostics(), baseline=baseline)
        adapter.execute_action(Action(operation="split"), baseline)

        update = adapter.handle_event(
            proto_event(
                common_pb2.EVENT_TIMER_SPLIT,
                timer_state=proto_timer_state(state_revision=3, split_index=1),
                event_sequence=1,
            )
        )

        self.assertIsNone(update)

    def test_reports_operation_rejection_without_retry(self) -> None:
        cases = (
            (common_pb2.OperationResponse(success=False, message="not allowed"), None),
            (None, BridgeRemoteError(12, "remote rejected")),
        )
        for response, error in cases:
            with self.subTest(error=error):
                client = create_autospec(BridgeRpcClient, instance=True)
                if error is None:
                    client.split.return_value = response
                    code = None
                    message = "not allowed"
                else:
                    client.split.side_effect = error
                    code = 12
                    message = "remote rejected"
                diagnostics = RecordingDiagnostics()
                action = Action(operation="split")

                outcome = self.make_adapter(client, diagnostics).execute_action(
                    action, domain_snapshot()
                )

                self.assertIs(outcome.execution, ActionExecution.DISPATCHED)
                self.assertIsNone(outcome.update)
                client.split.assert_called_once_with()
                self.assertEqual(
                    diagnostics.events,
                    [
                        (
                            "action_rejected",
                            LiveSplitConnection(54000),
                            action,
                            domain_snapshot(),
                            code,
                            message,
                        )
                    ],
                )

    def test_timeout_is_reported_as_unknown_without_retry(self) -> None:
        error = BridgeResponseTimeoutError("operation timed out")
        client = create_autospec(BridgeRpcClient, instance=True)
        client.split.side_effect = error
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")

        outcome = self.make_adapter(client, diagnostics).execute_action(
            action, domain_snapshot()
        )

        self.assertIs(outcome.execution, ActionExecution.UNKNOWN)
        client.split.assert_called_once_with()
        self.assertEqual(
            diagnostics.events,
            [
                (
                    "action_result_unknown",
                    LiveSplitConnection(54000),
                    action,
                    domain_snapshot(),
                    error,
                )
            ],
        )

    def test_protocol_failure_is_not_swallowed(self) -> None:
        error = BridgeProtocolError("invalid response")
        client = create_autospec(BridgeRpcClient, instance=True)
        client.split.side_effect = error
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")

        with self.assertRaises(BridgeProtocolError):
            self.make_adapter(client, diagnostics).execute_action(
                action, domain_snapshot()
            )

        client.split.assert_called_once_with()

    def test_success_without_timer_state_is_a_protocol_error(self) -> None:
        client = create_autospec(BridgeRpcClient, instance=True)
        client.split.return_value = common_pb2.OperationResponse(success=True)

        with self.assertRaisesRegex(BridgeProtocolError, "timer_state"):
            self.make_adapter(client, RecordingDiagnostics()).execute_action(
                Action(operation="split"), domain_snapshot()
            )


if __name__ == "__main__":
    unittest.main()
