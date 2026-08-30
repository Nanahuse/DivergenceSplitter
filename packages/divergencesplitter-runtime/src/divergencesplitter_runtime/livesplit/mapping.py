"""Convert LiveSplit.Bridge protobuf messages into runtime models."""

from livesplit_bridge import common_pb2

from divergencesplitter_runtime.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)

_PHASES = {
    common_pb2.NOT_RUNNING: TimerPhase.NOT_RUNNING,
    common_pb2.RUNNING: TimerPhase.RUNNING,
    common_pb2.PAUSED: TimerPhase.PAUSED,
    common_pb2.ENDED: TimerPhase.ENDED,
}

_TRANSITION_EVENTS = frozenset(
    (
        common_pb2.EVENT_TIMER_STARTED,
        common_pb2.EVENT_TIMER_SPLIT,
        common_pb2.EVENT_TIMER_SKIPPED,
        common_pb2.EVENT_TIMER_UNDO,
        common_pb2.EVENT_TIMER_RESET,
        common_pb2.EVENT_TIMER_PAUSED,
        common_pb2.EVENT_TIMER_RESUMED,
        common_pb2.EVENT_RUN_CHANGED,
    )
)

_PERIODIC_EVENTS = frozenset(
    (
        common_pb2.EVENT_GAME_TIME_INITIALIZED,
        common_pb2.EVENT_GAME_TIME_SET,
        common_pb2.EVENT_GAME_TIME_PAUSED,
        common_pb2.EVENT_GAME_TIME_RESUMED,
        common_pb2.EVENT_STATE_SNAPSHOT,
    )
)


def snapshot_from_proto(snapshot: common_pb2.TimerSnapshot) -> LiveSplitSnapshot:
    try:
        phase = _PHASES[snapshot.phase]
    except KeyError:
        phase_name = common_pb2.TimerPhase.Name(snapshot.phase)
        raise ValueError(f"unsupported timer phase: {phase_name}") from None
    return LiveSplitSnapshot(
        session_id=snapshot.session_id,
        state_revision=snapshot.state_revision,
        event_sequence=snapshot.event_sequence,
        phase=phase,
        split_index=snapshot.split_index,
        split_count=snapshot.split_count,
    )


def update_from_proto(event: common_pb2.BridgeEvent) -> LiveSplitUpdate:
    if not event.HasField("snapshot"):
        raise ValueError("Bridge event has no snapshot")
    if event.session_id != event.snapshot.session_id:
        raise ValueError("Bridge event and snapshot session IDs do not match")
    if event.event_sequence != event.snapshot.event_sequence:
        raise ValueError("Bridge event and snapshot sequences do not match")

    if event.type in _TRANSITION_EVENTS:
        kind = LiveSplitUpdateKind.TRANSITION
    elif event.type in _PERIODIC_EVENTS:
        kind = LiveSplitUpdateKind.PERIODIC
    else:
        event_name = common_pb2.BridgeEventType.Name(event.type)
        raise ValueError(f"unsupported Bridge event type: {event_name}")
    return LiveSplitUpdate(kind=kind, snapshot=snapshot_from_proto(event.snapshot))
