"""Convert LiveSplit.Bridge Protocol v4 models to runtime models."""

from livesplit_bridge import (
    EventType,
    RunState,
    TimerState,
)
from livesplit_bridge import (
    TimerPhase as BridgeTimerPhase,
)

from divergencesplitter_runtime.livesplit.models import (
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitSnapshot,
    LiveSplitTransitionReason,
    LiveSplitUpdateKind,
    TimerPhase,
)

_PHASES: dict[BridgeTimerPhase, TimerPhase] = {
    BridgeTimerPhase.NOT_RUNNING: TimerPhase.NOT_RUNNING,
    BridgeTimerPhase.RUNNING: TimerPhase.RUNNING,
    BridgeTimerPhase.PAUSED: TimerPhase.PAUSED,
    BridgeTimerPhase.ENDED: TimerPhase.ENDED,
}

_TRANSITION_EVENTS = frozenset(
    (
        EventType.TIMER_STARTED,
        EventType.TIMER_SPLIT,
        EventType.TIMER_SKIPPED,
        EventType.TIMER_UNDO,
        EventType.TIMER_RESET,
        EventType.TIMER_PHASE_CHANGED,
    )
)


def phase_from_bridge(phase: BridgeTimerPhase) -> TimerPhase:
    try:
        return _PHASES[BridgeTimerPhase(phase)]
    except KeyError, ValueError:
        raise ValueError(f"unsupported timer phase: {phase}") from None


def snapshot_from_timer_state(
    timer_state: TimerState,
    *,
    split_count: int,
) -> LiveSplitSnapshot:
    """Convert a Protocol v4 ``TimerState`` and Run-derived split count."""

    return LiveSplitSnapshot(
        phase=phase_from_bridge(timer_state.phase),
        split_index=timer_state.split_index,
        split_count=split_count,
    )


def run_info_from_run(run: RunState) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        game_name=run.game_name,
        category_name=run.category_name,
        segments=tuple(
            LiveSplitSegmentInfo(index=segment.index, name=segment.name)
            for segment in run.segments
        ),
    )


def event_update_kind(event_type: EventType) -> LiveSplitUpdateKind | None:
    """Classify state-changing events; context changes only advance the cursor."""

    event_type = EventType(event_type)
    if event_type in _TRANSITION_EVENTS:
        return LiveSplitUpdateKind.TRANSITION
    if event_type is EventType.RUN_CHANGED:
        return LiveSplitUpdateKind.RUN_CHANGED
    if event_type is EventType.CONTEXT_CHANGED:
        return None
    raise ValueError(f"unsupported Bridge event type: {event_type}")


_TRANSITION_REASONS: dict[EventType, LiveSplitTransitionReason] = {
    EventType.TIMER_STARTED: LiveSplitTransitionReason.START,
    EventType.TIMER_SPLIT: LiveSplitTransitionReason.SPLIT,
    EventType.TIMER_SKIPPED: LiveSplitTransitionReason.SKIP,
    EventType.TIMER_UNDO: LiveSplitTransitionReason.UNDO,
    EventType.TIMER_RESET: LiveSplitTransitionReason.RESET,
}


def transition_reason_from_event(
    event_type: EventType,
    snapshot: LiveSplitSnapshot,
) -> LiveSplitTransitionReason:
    """Classify a timer transition without leaking client types upward."""

    event_type = EventType(event_type)
    if event_type is EventType.TIMER_PHASE_CHANGED:
        if snapshot.phase is TimerPhase.PAUSED:
            return LiveSplitTransitionReason.PAUSE
        if snapshot.phase is TimerPhase.RUNNING:
            return LiveSplitTransitionReason.RESUME
        if snapshot.phase is TimerPhase.NOT_RUNNING:
            return LiveSplitTransitionReason.RESET
        return LiveSplitTransitionReason.OTHER
    return _TRANSITION_REASONS.get(event_type, LiveSplitTransitionReason.OTHER)
