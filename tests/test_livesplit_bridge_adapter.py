from __future__ import annotations

import pytest
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

from divergencesplitter.livesplit_bridge_adapter import (
    LiveSplitBridgeConversionError,
    event_update,
    snapshot_update,
    timer_operation_for_action,
    to_livesplit_snapshot,
)
from divergencesplitter.models import LiveSplitUpdateKind, TimerPhase
from divergencesplitter.rule import Action


def snapshot(phase: BridgeTimerPhase = BridgeTimerPhase.RUNNING) -> BridgeTimerSnapshot:
    return BridgeTimerSnapshot(
        state_revision=2,
        session_id=3,
        event_sequence=4,
        phase=phase,
        split_index=0,
        split_count=2,
        real_time_ticks=None,
        game_time_ticks=None,
        is_paused=False,
        is_game_time_initialized=False,
    )


def test_snapshot_conversion_injects_target() -> None:
    converted = to_livesplit_snapshot(snapshot(), target_id="main")
    assert converted.target_id == "main"
    assert converted.phase is TimerPhase.RUNNING


def test_starting_phase_is_not_an_application_state() -> None:
    with pytest.raises(LiveSplitBridgeConversionError, match="STARTING"):
        to_livesplit_snapshot(snapshot(BridgeTimerPhase.STARTING), target_id="main")


def test_snapshot_kind_must_be_initial_or_resync() -> None:
    with pytest.raises(LiveSplitBridgeConversionError, match="INITIAL or RESYNC"):
        snapshot_update(
            snapshot(),
            target_id="main",
            kind=LiveSplitUpdateKind.PERIODIC,
        )


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (BridgeEventType.TIMER_SPLIT, LiveSplitUpdateKind.TRANSITION),
        (BridgeEventType.RUN_CHANGED, LiveSplitUpdateKind.TRANSITION),
        (BridgeEventType.STATE_SNAPSHOT, LiveSplitUpdateKind.PERIODIC),
        (BridgeEventType.GAME_TIME_SET, LiveSplitUpdateKind.PERIODIC),
    ],
)
def test_event_kind_mapping(
    event_type: BridgeEventType,
    expected: LiveSplitUpdateKind,
) -> None:
    event = BridgeEvent(
        session_id=3,
        event_sequence=4,
        type=event_type,
        snapshot=snapshot(),
        description="event",
    )
    assert event_update(event, target_id="main").kind is expected


def test_action_operation_mapping() -> None:
    action = Action(scenario_id="scenario", target_id="main", operation="split")
    assert timer_operation_for_action(action) is TimerOperation.SPLIT
