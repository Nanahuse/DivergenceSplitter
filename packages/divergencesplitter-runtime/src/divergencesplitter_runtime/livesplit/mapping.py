"""Convert LiveSplit.Bridge Protocol v3 protobuf messages to runtime models."""

from livesplit_bridge import common_pb2, run_pb2

from divergencesplitter_runtime.livesplit.models import (
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitSnapshot,
    LiveSplitUpdateKind,
    TimerPhase,
)

_PHASES: dict[int, TimerPhase] = {
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
        common_pb2.EVENT_TIMER_PHASE_CHANGED,
    )
)


def phase_from_proto(phase_value: int) -> TimerPhase:
    try:
        return _PHASES[phase_value]
    except KeyError:
        phase_name = common_pb2.TimerPhase.Name(phase_value)
        raise ValueError(f"unsupported timer phase: {phase_name}") from None


def snapshot_from_timer_state(
    timer_state: common_pb2.TimerState,
    *,
    split_count: int,
) -> LiveSplitSnapshot:
    """Convert a Protocol v3 ``TimerState`` and Run-derived split count."""

    return LiveSplitSnapshot(
        phase=phase_from_proto(timer_state.phase),
        split_index=timer_state.split_index,
        split_count=split_count,
    )


def run_info_from_proto(run: run_pb2.RunState) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        game_name=run.game_name,
        category_name=run.category_name,
        segments=tuple(
            LiveSplitSegmentInfo(index=segment.index, name=segment.name)
            for segment in run.segments
        ),
    )


def event_update_kind(event_type: int) -> LiveSplitUpdateKind | None:
    """Classify state-changing events; context changes only advance the cursor."""

    if event_type in _TRANSITION_EVENTS:
        return LiveSplitUpdateKind.TRANSITION
    if event_type == common_pb2.EVENT_RUN_CHANGED:
        return LiveSplitUpdateKind.RUN_CHANGED
    if event_type == common_pb2.EVENT_CONTEXT_CHANGED:
        return None
    event_name = common_pb2.BridgeEventType.Name(event_type)
    raise ValueError(f"unsupported Bridge event type: {event_name}")
