from __future__ import annotations

import pytest

from livesplit_bridge_client import (
    AttachResult,
    BridgeEvent,
    BridgeEventType,
    OperationResult,
    TimerPhase,
    TimerSnapshot,
)


def snapshot() -> TimerSnapshot:
    return TimerSnapshot(
        state_revision=3,
        session_id=7,
        event_sequence=11,
        phase=TimerPhase.RUNNING,
        split_index=1,
        split_count=4,
        real_time_ticks=None,
        game_time_ticks=120,
        is_paused=False,
        is_game_time_initialized=True,
    )


def test_attach_requires_matching_session() -> None:
    with pytest.raises(ValueError, match="must match"):
        AttachResult(session_id=8, snapshot=snapshot())


def test_successful_operation_requires_snapshot() -> None:
    with pytest.raises(ValueError, match="must include"):
        OperationResult(success=True, message="OK", snapshot=None)


def test_failed_operation_may_omit_snapshot() -> None:
    result = OperationResult(success=False, message="rejected", snapshot=None)
    assert result.snapshot is None


def test_event_requires_matching_identity() -> None:
    with pytest.raises(ValueError, match="event_sequence"):
        BridgeEvent(
            session_id=7,
            event_sequence=12,
            type=BridgeEventType.TIMER_SPLIT,
            snapshot=snapshot(),
            description="split",
        )
