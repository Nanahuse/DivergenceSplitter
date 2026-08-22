from __future__ import annotations

from livesplit_bridge_client import (
    BridgeEvent,
    BridgeEventType,
    TimerOperation,
)
from livesplit_bridge_client import (
    TimerPhase as BridgeTimerPhase,
)
from livesplit_bridge_client import (
    TimerSnapshot as BridgeTimerSnapshot,
)

from divergencesplitter.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)
from divergencesplitter.rule import Action


class LiveSplitBridgeConversionError(ValueError):
    """A valid Bridge DTO cannot be represented by the application domain."""


_PHASES = {
    BridgeTimerPhase.NOT_RUNNING: TimerPhase.NOT_RUNNING,
    BridgeTimerPhase.RUNNING: TimerPhase.RUNNING,
    BridgeTimerPhase.PAUSED: TimerPhase.PAUSED,
    BridgeTimerPhase.ENDED: TimerPhase.ENDED,
}

_TRANSITION_EVENTS = {
    BridgeEventType.TIMER_STARTED,
    BridgeEventType.TIMER_SPLIT,
    BridgeEventType.TIMER_SKIPPED,
    BridgeEventType.TIMER_UNDO,
    BridgeEventType.TIMER_RESET,
    BridgeEventType.TIMER_PAUSED,
    BridgeEventType.TIMER_RESUMED,
    BridgeEventType.RUN_CHANGED,
}

_OPERATIONS = {
    "split": TimerOperation.SPLIT,
    "skip": TimerOperation.SKIP,
    "undo": TimerOperation.UNDO,
    "reset": TimerOperation.RESET,
    "pause": TimerOperation.PAUSE,
    "resume": TimerOperation.RESUME,
}


def to_livesplit_snapshot(
    snapshot: BridgeTimerSnapshot,
    *,
    target_id: str,
) -> LiveSplitSnapshot:
    if not target_id:
        raise LiveSplitBridgeConversionError("target_id must not be empty")
    try:
        phase = _PHASES[snapshot.phase]
    except KeyError as error:
        raise LiveSplitBridgeConversionError(
            f"Unsupported application timer phase: {snapshot.phase.name}"
        ) from error
    try:
        return LiveSplitSnapshot(
            target_id=target_id,
            session_id=snapshot.session_id,
            state_revision=snapshot.state_revision,
            event_sequence=snapshot.event_sequence,
            phase=phase,
            split_index=snapshot.split_index,
            split_count=snapshot.split_count,
        )
    except (TypeError, ValueError) as error:
        raise LiveSplitBridgeConversionError(str(error)) from error


def snapshot_update(
    snapshot: BridgeTimerSnapshot,
    *,
    target_id: str,
    kind: LiveSplitUpdateKind,
) -> LiveSplitUpdate:
    if kind not in (LiveSplitUpdateKind.INITIAL, LiveSplitUpdateKind.RESYNC):
        raise LiveSplitBridgeConversionError(
            "snapshot updates must be explicitly INITIAL or RESYNC"
        )
    return LiveSplitUpdate(
        kind=kind,
        snapshot=to_livesplit_snapshot(snapshot, target_id=target_id),
    )


def event_update(event: BridgeEvent, *, target_id: str) -> LiveSplitUpdate:
    kind = (
        LiveSplitUpdateKind.TRANSITION
        if event.type in _TRANSITION_EVENTS
        else LiveSplitUpdateKind.PERIODIC
    )
    return LiveSplitUpdate(
        kind=kind,
        snapshot=to_livesplit_snapshot(event.snapshot, target_id=target_id),
    )


def timer_operation_for_action(action: Action) -> TimerOperation:
    try:
        return _OPERATIONS[action.operation]
    except KeyError as error:
        raise LiveSplitBridgeConversionError(
            f"Unsupported Action operation: {action.operation}"
        ) from error
