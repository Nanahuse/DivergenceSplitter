import unittest
from unittest.mock import create_autospec, patch

from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime import (
    LiveSplitBridgeAdapter,
    LiveSplitSnapshot,
    LiveSplitUpdateKind,
    TimerPhase,
)
from divergencesplitter_runtime.livesplit import (
    snapshot_from_proto,
    update_from_proto,
)
from livesplit_bridge import (
    BridgeClient,
    BridgeEventSubscriber,
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
    def test_uses_connection_endpoints_for_client_instances(self) -> None:
        connection = LiveSplitConnection("tcp://rpc", "tcp://event")
        with (
            patch(
                "divergencesplitter_runtime.livesplit.adapter.BridgeClient",
                autospec=True,
            ) as client_type,
            patch(
                "divergencesplitter_runtime.livesplit.adapter.BridgeEventSubscriber",
                autospec=True,
            ) as subscriber_type,
        ):
            adapter = LiveSplitBridgeAdapter(
                connection,
                rpc_timeout_ms=10,
                event_timeout_ms=20,
            )
            adapter.close()

        client_type.assert_called_once_with("tcp://rpc", timeout_ms=10)
        subscriber_type.assert_called_once_with("tcp://event", timeout_ms=20)
        subscriber_type.return_value.close.assert_called_once_with()
        client_type.return_value.close.assert_called_once_with()

    def test_converts_client_snapshot_and_subscriber_event(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        subscriber = create_autospec(BridgeEventSubscriber, instance=True)
        client.snapshot.return_value = proto_snapshot()
        subscriber.receive.return_value = proto_event(common_pb2.EVENT_TIMER_SPLIT)

        with LiveSplitBridgeAdapter(
            LiveSplitConnection("rpc", "event"),
            client=client,
            subscriber=subscriber,
        ) as adapter:
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
            self.assertIs(
                adapter.receive(timeout_ms=15).kind,
                LiveSplitUpdateKind.TRANSITION,
            )

        subscriber.receive.assert_called_once_with(timeout_ms=15)
        subscriber.close.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_closes_constructed_client_when_subscriber_construction_fails(self) -> None:
        with (
            patch(
                "divergencesplitter_runtime.livesplit.adapter.BridgeClient",
                autospec=True,
            ) as client_type,
            patch(
                "divergencesplitter_runtime.livesplit.adapter.BridgeEventSubscriber",
                autospec=True,
                side_effect=RuntimeError("subscriber failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "subscriber failed"),
        ):
            LiveSplitBridgeAdapter(LiveSplitConnection("rpc", "event"))

        client_type.return_value.close.assert_called_once_with()

    def test_close_is_idempotent(self) -> None:
        client = create_autospec(BridgeClient, instance=True)
        subscriber = create_autospec(BridgeEventSubscriber, instance=True)
        adapter = LiveSplitBridgeAdapter(
            LiveSplitConnection("rpc", "event"),
            client=client,
            subscriber=subscriber,
        )

        adapter.close()
        adapter.close()

        subscriber.close.assert_called_once_with()
        client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
