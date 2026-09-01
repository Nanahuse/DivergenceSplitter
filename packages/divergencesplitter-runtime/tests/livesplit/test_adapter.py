import unittest
from unittest.mock import create_autospec, patch

from divergencesplitter import Action, LiveSplitConnection
from divergencesplitter_runtime import (
    LiveSplitBridgeAdapter,
    LiveSplitBridgeDiagnostics,
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)
from divergencesplitter_runtime.livesplit import (
    snapshot_from_proto,
    update_from_proto,
)
from livesplit_bridge import (
    BridgeClient,
    BridgeConnectionLostError,
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeResponseTimeoutError,
    bridge_pb2,
    common_pb2,
)


def proto_snapshot(
    *,
    session_id: int = 1,
    state_revision: int = 2,
    event_sequence: int = 3,
    phase: common_pb2.TimerPhase = common_pb2.RUNNING,
    split_index: int = 0,
    split_count: int = 2,
) -> common_pb2.TimerSnapshot:
    return common_pb2.TimerSnapshot(
        session_id=session_id,
        state_revision=state_revision,
        event_sequence=event_sequence,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


def proto_event(
    event_type: common_pb2.BridgeEventType,
    *,
    snapshot: common_pb2.TimerSnapshot | None = None,
) -> common_pb2.BridgeEvent:
    if snapshot is None:
        snapshot = proto_snapshot()
    return common_pb2.BridgeEvent(
        session_id=snapshot.session_id,
        event_sequence=snapshot.event_sequence,
        type=event_type,
        snapshot=snapshot,
    )


def domain_snapshot(
    *,
    session_id: int = 1,
    state_revision: int = 2,
    event_sequence: int = 3,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 2,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=session_id,
        state_revision=state_revision,
        event_sequence=event_sequence,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


class RecordingDiagnostics(LiveSplitBridgeDiagnostics):
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.stream_events: list[tuple[object, ...]] = []

    def snapshot_failed(self, action: Action, error: Exception) -> None:
        self.events.append(("snapshot_failed", action, error))

    def snapshot_mismatched(
        self,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None:
        self.events.append(("snapshot_mismatched", action, expected, actual))

    def action_precondition_failed(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self.events.append(("action_precondition_failed", action, snapshot))

    def action_succeeded(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self.events.append(("action_succeeded", action, snapshot))

    def action_rejected(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None:
        self.events.append(("action_rejected", action, snapshot, code, message))

    def action_result_unknown(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None:
        self.events.append(("action_result_unknown", action, snapshot, error))

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
            (common_pb2.NOT_RUNNING, -1, 0, TimerPhase.NOT_RUNNING),
            (common_pb2.RUNNING, 0, 2, TimerPhase.RUNNING),
            (common_pb2.PAUSED, 0, 2, TimerPhase.PAUSED),
            (common_pb2.ENDED, 2, 2, TimerPhase.ENDED),
        )
        for proto_phase, split_index, split_count, expected in cases:
            with self.subTest(proto_phase=proto_phase):
                actual = snapshot_from_proto(
                    proto_snapshot(
                        phase=proto_phase,
                        split_index=split_index,
                        split_count=split_count,
                    )
                )
                self.assertEqual(actual.phase, expected)
                self.assertEqual(actual.session_id, 1)
                self.assertEqual(actual.state_revision, 2)
                self.assertEqual(actual.event_sequence, 3)

    def test_snapshot_rejects_unsupported_phases(self) -> None:
        for phase in (common_pb2.TIMER_PHASE_UNSPECIFIED, common_pb2.STARTING):
            with (
                self.subTest(phase=phase),
                self.assertRaisesRegex(ValueError, "unsupported timer phase"),
            ):
                snapshot_from_proto(proto_snapshot(phase=phase))

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
                update = update_from_proto(proto_event(event_type))
                self.assertIs(update.kind, LiveSplitUpdateKind.TRANSITION)

    def test_snapshot_and_game_time_events_are_periodic(self) -> None:
        event_types = (
            common_pb2.EVENT_GAME_TIME_INITIALIZED,
            common_pb2.EVENT_GAME_TIME_SET,
            common_pb2.EVENT_GAME_TIME_PAUSED,
            common_pb2.EVENT_GAME_TIME_RESUMED,
            common_pb2.EVENT_STATE_SNAPSHOT,
        )
        for event_type in event_types:
            with self.subTest(event_type=event_type):
                update = update_from_proto(proto_event(event_type))
                self.assertIs(update.kind, LiveSplitUpdateKind.PERIODIC)

    def test_event_rejects_missing_snapshot(self) -> None:
        event = common_pb2.BridgeEvent(
            session_id=1,
            event_sequence=3,
            type=common_pb2.EVENT_TIMER_SPLIT,
        )
        with self.assertRaisesRegex(ValueError, "no snapshot"):
            update_from_proto(event)

    def test_event_rejects_envelope_mismatch(self) -> None:
        event = proto_event(common_pb2.EVENT_TIMER_SPLIT)
        event.session_id += 1
        with self.assertRaisesRegex(ValueError, "session IDs"):
            update_from_proto(event)

        event = proto_event(common_pb2.EVENT_TIMER_SPLIT)
        event.event_sequence += 1
        with self.assertRaisesRegex(ValueError, "sequences"):
            update_from_proto(event)

    def test_event_rejects_unspecified_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported Bridge event type"):
            update_from_proto(proto_event(common_pb2.BRIDGE_EVENT_UNSPECIFIED))


class AdapterTest(unittest.TestCase):
    def test_uses_connection_endpoints_for_integrated_client(self) -> None:
        connection = LiveSplitConnection("tcp://rpc", "tcp://event")
        with patch(
            "divergencesplitter_runtime.livesplit.adapter.BridgeClient",
            autospec=True,
        ) as client_type:
            adapter = LiveSplitBridgeAdapter(
                connection,
                diagnostics=RecordingDiagnostics(),
                rpc_timeout_ms=10,
                heartbeat_timeout_ms=20,
            )
            adapter.close()

        client_type.assert_called_once_with(
            "tcp://rpc",
            "tcp://event",
            response_timeout_ms=10,
            heartbeat_timeout_ms=20,
        )
        client_type.return_value.close.assert_called_once_with()

    def test_attach_establishes_initial_snapshot_and_converts_events(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            snapshot=proto_snapshot(event_sequence=2),
        )
        client.snapshot.return_value = proto_snapshot()
        client.receive.return_value = proto_event(common_pb2.EVENT_TIMER_SPLIT)

        with LiveSplitBridgeAdapter(
            LiveSplitConnection("rpc", "event"),
            diagnostics=RecordingDiagnostics(),
            client=client,
        ) as adapter:
            initial = adapter.attach()
            self.assertIs(initial.kind, LiveSplitUpdateKind.INITIAL)
            self.assertEqual(
                adapter.snapshot(),
                LiveSplitSnapshot(
                    session_id=1,
                    state_revision=2,
                    event_sequence=3,
                    phase=TimerPhase.RUNNING,
                    split_index=0,
                    split_count=2,
                ),
            )
            update = adapter.receive(timeout_ms=15)
            self.assertIsNotNone(update)
            assert isinstance(update, LiveSplitUpdate)
            self.assertIs(update.kind, LiveSplitUpdateKind.TRANSITION)

        client.receive.assert_called_once_with(timeout_ms=15)
        client.close.assert_called_once_with()

    def test_heartbeat_is_consumed_and_next_sequence_requests_resync(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            snapshot=proto_snapshot(event_sequence=3),
        )
        client.receive.side_effect = (
            common_pb2.BridgeEvent(
                session_id=1,
                event_sequence=3,
                type=common_pb2.EVENT_HEARTBEAT,
            ),
            common_pb2.BridgeEvent(
                session_id=1,
                event_sequence=4,
                type=common_pb2.EVENT_HEARTBEAT,
            ),
        )
        client.snapshot.return_value = proto_snapshot(event_sequence=4)
        diagnostics = RecordingDiagnostics()
        connection = LiveSplitConnection("rpc", "event")
        adapter = LiveSplitBridgeAdapter(
            connection,
            diagnostics=diagnostics,
            client=client,
        )
        adapter.attach()

        self.assertIsNone(adapter.receive(timeout_ms=0))
        reason = adapter.receive(timeout_ms=0)

        self.assertIs(reason, LiveSplitResyncReason.GAP)
        assert isinstance(reason, LiveSplitResyncReason)
        update = adapter.resync(reason)
        self.assertIs(update.kind, LiveSplitUpdateKind.RESYNC)
        self.assertEqual(update.snapshot.event_sequence, 4)
        client.snapshot.assert_called_once_with()
        self.assertEqual(
            diagnostics.stream_events[:3],
            [
                ("heartbeat_received", connection, 1, 3),
                ("heartbeat_received", connection, 1, 4),
                (
                    "gap_detected",
                    connection,
                    domain_snapshot(event_sequence=3),
                    1,
                    4,
                ),
            ],
        )
        self.assertEqual(
            diagnostics.stream_events[3:],
            [
                ("resync_started", connection, LiveSplitResyncReason.GAP),
                (
                    "resync_completed",
                    connection,
                    LiveSplitResyncReason.GAP,
                    domain_snapshot(event_sequence=3),
                    domain_snapshot(event_sequence=4),
                ),
            ],
        )

    def test_connection_loss_marks_unsynchronized_until_reconnect(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        client.attach.return_value = bridge_pb2.AttachResponse(
            session_id=1,
            snapshot=proto_snapshot(),
        )
        client.receive.side_effect = BridgeConnectionLostError("lost")
        client.reconnect.return_value = proto_snapshot(session_id=2, event_sequence=0)
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection("rpc", "event"),
            diagnostics=RecordingDiagnostics(),
            client=client,
        )
        adapter.attach()

        with self.assertRaises(BridgeConnectionLostError):
            adapter.receive(timeout_ms=0)

        update = adapter.reconnect()

        self.assertIs(update.kind, LiveSplitUpdateKind.RESYNC)

    def test_close_is_idempotent(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection("rpc", "event"),
            diagnostics=RecordingDiagnostics(),
            client=client,
        )

        adapter.close()
        adapter.close()

        client.close.assert_called_once_with()


class ActionExecutionTest(unittest.TestCase):
    def make_adapter(
        self,
        client: BridgeClient,
        diagnostics: LiveSplitBridgeDiagnostics,
    ) -> LiveSplitBridgeAdapter:
        return LiveSplitBridgeAdapter(
            LiveSplitConnection("rpc", "event"),
            diagnostics=diagnostics,
            client=client,
        )

    def assert_no_operation(self, client: BridgeClient) -> None:
        for operation in ("split", "skip", "undo", "reset", "pause", "resume"):
            getattr(client, operation).assert_not_called()

    def test_maps_each_action_to_one_client_operation(self) -> None:
        cases = (
            ("split", common_pb2.RUNNING, 0, 2),
            ("skip", common_pb2.RUNNING, 0, 2),
            ("undo", common_pb2.PAUSED, 1, 2),
            ("reset", common_pb2.ENDED, 2, 2),
            ("pause", common_pb2.RUNNING, 0, 2),
            ("resume", common_pb2.PAUSED, 0, 2),
        )
        for operation, phase, split_index, split_count in cases:
            with self.subTest(operation=operation):
                client = create_autospec(BridgeClient, instance=True)
                client.snapshot.return_value = proto_snapshot(
                    phase=phase,
                    split_index=split_index,
                    split_count=split_count,
                )
                getattr(client, operation).return_value = common_pb2.OperationResponse(
                    success=True
                )
                diagnostics = RecordingDiagnostics()
                action = Action(operation=operation)
                adapter = self.make_adapter(client, diagnostics)

                result = adapter.execute_action(
                    action,
                    snapshot_from_proto(client.snapshot.return_value),
                )

                self.assertIsNone(result)
                client.snapshot.assert_called_once_with()
                getattr(client, operation).assert_called_once_with()
                expected = snapshot_from_proto(client.snapshot.return_value)
                self.assertEqual(
                    diagnostics.events,
                    [("action_succeeded", action, expected)],
                )

    def test_compares_expected_state_but_ignores_event_sequence(self) -> None:
        expected = domain_snapshot()
        changed_states = (
            domain_snapshot(session_id=2),
            domain_snapshot(state_revision=3),
            domain_snapshot(phase=TimerPhase.PAUSED),
            domain_snapshot(split_index=1),
            domain_snapshot(split_count=3),
        )
        for actual in changed_states:
            with self.subTest(actual=actual):
                client = create_autospec(BridgeClient, instance=True)
                client.snapshot.return_value = proto_snapshot(
                    session_id=actual.session_id,
                    state_revision=actual.state_revision,
                    event_sequence=actual.event_sequence,
                    phase={
                        TimerPhase.RUNNING: common_pb2.RUNNING,
                        TimerPhase.PAUSED: common_pb2.PAUSED,
                    }[actual.phase],
                    split_index=actual.split_index,
                    split_count=actual.split_count,
                )
                diagnostics = RecordingDiagnostics()
                action = Action(operation="split")

                self.make_adapter(client, diagnostics).execute_action(action, expected)

                self.assert_no_operation(client)
                self.assertEqual(
                    diagnostics.events,
                    [("snapshot_mismatched", action, expected, actual)],
                )

        client = create_autospec(BridgeClient, instance=True)
        client.snapshot.return_value = proto_snapshot(event_sequence=99)
        client.split.return_value = common_pb2.OperationResponse(success=True)
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")

        self.make_adapter(client, diagnostics).execute_action(action, expected)

        client.split.assert_called_once_with()
        actual = domain_snapshot(event_sequence=99)
        self.assertEqual(
            diagnostics.events,
            [("action_succeeded", action, actual)],
        )

    def test_rejects_actions_whose_phase_or_position_is_invalid(self) -> None:
        cases = (
            ("split", common_pb2.PAUSED, 0, 2),
            ("skip", common_pb2.RUNNING, 1, 2),
            ("undo", common_pb2.RUNNING, 0, 2),
            ("undo", common_pb2.PAUSED, 0, 2),
            ("reset", common_pb2.NOT_RUNNING, -1, 2),
            ("pause", common_pb2.PAUSED, 0, 2),
            ("resume", common_pb2.RUNNING, 0, 2),
        )
        for operation, phase, split_index, split_count in cases:
            with self.subTest(operation=operation, phase=phase):
                client = create_autospec(BridgeClient, instance=True)
                client.snapshot.return_value = proto_snapshot(
                    phase=phase,
                    split_index=split_index,
                    split_count=split_count,
                )
                diagnostics = RecordingDiagnostics()
                action = Action(operation=operation)
                snapshot = snapshot_from_proto(client.snapshot.return_value)

                self.make_adapter(client, diagnostics).execute_action(action, snapshot)

                self.assert_no_operation(client)
                self.assertEqual(
                    diagnostics.events,
                    [("action_precondition_failed", action, snapshot)],
                )

    def test_snapshot_failure_does_not_send_an_operation(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        error = BridgeResponseTimeoutError("snapshot timed out")
        client.snapshot.side_effect = error
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")

        self.make_adapter(client, diagnostics).execute_action(action, domain_snapshot())

        self.assert_no_operation(client)
        self.assertEqual(diagnostics.events, [("snapshot_failed", action, error)])

    def test_reports_operation_rejection_without_retry(self) -> None:
        cases = (
            (common_pb2.OperationResponse(success=False, message="not allowed"), None),
            (None, BridgeRemoteError(12, "remote rejected")),
        )
        for response, error in cases:
            with self.subTest(error=error):
                client = create_autospec(BridgeClient, instance=True)
                client.snapshot.return_value = proto_snapshot()
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

                self.make_adapter(client, diagnostics).execute_action(
                    action, domain_snapshot()
                )

                client.split.assert_called_once_with()
                self.assertEqual(
                    diagnostics.events,
                    [("action_rejected", action, domain_snapshot(), code, message)],
                )

    def test_reports_unknown_operation_result_without_retry(self) -> None:
        for error in (
            BridgeResponseTimeoutError("operation timed out"),
            BridgeProtocolError("invalid response"),
        ):
            with self.subTest(error=error):
                client = create_autospec(BridgeClient, instance=True)
                client.snapshot.return_value = proto_snapshot()
                client.split.side_effect = error
                diagnostics = RecordingDiagnostics()
                action = Action(operation="split")

                self.make_adapter(client, diagnostics).execute_action(
                    action, domain_snapshot()
                )

                client.split.assert_called_once_with()
                self.assertEqual(
                    diagnostics.events,
                    [("action_result_unknown", action, domain_snapshot(), error)],
                )

    def test_does_not_map_the_operation_response_snapshot(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        client.snapshot.return_value = proto_snapshot()
        client.split.return_value = common_pb2.OperationResponse(
            success=True,
            snapshot=proto_snapshot(phase=common_pb2.TIMER_PHASE_UNSPECIFIED),
        )
        diagnostics = RecordingDiagnostics()
        action = Action(operation="split")

        self.make_adapter(client, diagnostics).execute_action(action, domain_snapshot())

        self.assertEqual(
            diagnostics.events,
            [("action_succeeded", action, domain_snapshot())],
        )


if __name__ == "__main__":
    unittest.main()
