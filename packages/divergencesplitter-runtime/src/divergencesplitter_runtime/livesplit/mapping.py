"""Convert LiveSplit.Bridge Protocol v2 protobuf messages into runtime models."""

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
    common_pb2.STARTING: TimerPhase.STARTING,
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
    )
)

# Runtime-only changes advance the event cursor but do not change the state the
# scenario rules evaluate, so they produce no scenario transition.
_IGNORED_EVENTS = frozenset((common_pb2.EVENT_RUNTIME_CHANGED,))


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
    """Convert a Protocol v2 ``TimerState`` plus a run-derived split count."""

    return LiveSplitSnapshot(
        session_id=timer_state.session_id,
        state_revision=timer_state.state_revision,
        run_revision=timer_state.run_revision,
        phase=phase_from_proto(timer_state.phase),
        split_index=timer_state.split_index,
        split_count=split_count,
    )


def run_info_from_proto(run: run_pb2.RunState) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=run.session_id,
        run_revision=run.run_revision,
        segments=tuple(
            LiveSplitSegmentInfo(index=segment.index, name=segment.name)
            for segment in run.segments
        ),
    )


def event_update_kind(event_type: int) -> LiveSplitUpdateKind | None:
    """Classify one state event, or ``None`` when it carries no scenario change."""

    if event_type in _TRANSITION_EVENTS:
        return LiveSplitUpdateKind.TRANSITION
    if event_type in _PERIODIC_EVENTS:
        return LiveSplitUpdateKind.PERIODIC
    if event_type in _IGNORED_EVENTS:
        return None
    event_name = common_pb2.BridgeEventType.Name(event_type)
    raise ValueError(f"unsupported Bridge event type: {event_name}")
