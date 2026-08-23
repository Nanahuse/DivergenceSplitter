from __future__ import annotations

from google.protobuf.message import Message
from livesplit.bridge.v1 import bridge_pb2, common_pb2

from livesplit_bridge_client.errors import BridgeProtocolError
from livesplit_bridge_client.models import (
    AttachResult,
    BridgeEvent,
    BridgeEventType,
    OperationResult,
    TimerOperation,
    TimerPhase,
    TimerSnapshot,
)

_PHASES = {
    common_pb2.NOT_RUNNING: TimerPhase.NOT_RUNNING,
    common_pb2.STARTING: TimerPhase.STARTING,
    common_pb2.RUNNING: TimerPhase.RUNNING,
    common_pb2.PAUSED: TimerPhase.PAUSED,
    common_pb2.ENDED: TimerPhase.ENDED,
}

_OPERATIONS = {
    TimerOperation.START: common_pb2.TIMER_START,
    TimerOperation.SPLIT: common_pb2.TIMER_SPLIT,
    TimerOperation.SKIP: common_pb2.TIMER_SKIP,
    TimerOperation.UNDO: common_pb2.TIMER_UNDO,
    TimerOperation.RESET: common_pb2.TIMER_RESET,
    TimerOperation.PAUSE: common_pb2.TIMER_PAUSE,
    TimerOperation.RESUME: common_pb2.TIMER_RESUME,
}

_EVENT_TYPES = {
    common_pb2.EVENT_TIMER_STARTED: BridgeEventType.TIMER_STARTED,
    common_pb2.EVENT_TIMER_SPLIT: BridgeEventType.TIMER_SPLIT,
    common_pb2.EVENT_TIMER_SKIPPED: BridgeEventType.TIMER_SKIPPED,
    common_pb2.EVENT_TIMER_UNDO: BridgeEventType.TIMER_UNDO,
    common_pb2.EVENT_TIMER_RESET: BridgeEventType.TIMER_RESET,
    common_pb2.EVENT_TIMER_PAUSED: BridgeEventType.TIMER_PAUSED,
    common_pb2.EVENT_TIMER_RESUMED: BridgeEventType.TIMER_RESUMED,
    common_pb2.EVENT_GAME_TIME_INITIALIZED: BridgeEventType.GAME_TIME_INITIALIZED,
    common_pb2.EVENT_GAME_TIME_SET: BridgeEventType.GAME_TIME_SET,
    common_pb2.EVENT_GAME_TIME_PAUSED: BridgeEventType.GAME_TIME_PAUSED,
    common_pb2.EVENT_GAME_TIME_RESUMED: BridgeEventType.GAME_TIME_RESUMED,
    common_pb2.EVENT_RUN_CHANGED: BridgeEventType.RUN_CHANGED,
    common_pb2.EVENT_STATE_SNAPSHOT: BridgeEventType.STATE_SNAPSHOT,
}


def timer_operation_value(operation: TimerOperation) -> common_pb2.TimerOperationType:
    if not isinstance(operation, TimerOperation):
        raise TypeError("operation must be a TimerOperation")
    return _OPERATIONS[operation]


def timer_snapshot(message: common_pb2.TimerSnapshot) -> TimerSnapshot:
    try:
        phase = _PHASES[message.phase]
    except KeyError as error:
        raise BridgeProtocolError(
            f"Unsupported timer phase: {message.phase}"
        ) from error
    try:
        return TimerSnapshot(
            state_revision=message.state_revision,
            session_id=message.session_id,
            event_sequence=message.event_sequence,
            phase=phase,
            split_index=message.split_index,
            split_count=message.split_count,
            real_time_ticks=message.real_time_ticks
            if message.HasField("real_time_ticks")
            else None,
            game_time_ticks=message.game_time_ticks
            if message.HasField("game_time_ticks")
            else None,
            is_paused=message.is_paused,
            is_game_time_initialized=message.is_game_time_initialized,
        )
    except (TypeError, ValueError) as error:
        raise BridgeProtocolError(f"Invalid timer snapshot: {error}") from error


def attach_result(message: bridge_pb2.AttachResponse) -> AttachResult:
    if not message.HasField("snapshot"):
        raise BridgeProtocolError("Attach response has no snapshot")
    try:
        return AttachResult(
            session_id=message.session_id,
            snapshot=timer_snapshot(message.snapshot),
        )
    except ValueError as error:
        raise BridgeProtocolError(str(error)) from error


def operation_result(message: common_pb2.OperationResponse) -> OperationResult:
    snapshot = (
        timer_snapshot(message.snapshot) if message.HasField("snapshot") else None
    )
    try:
        return OperationResult(
            success=message.success,
            message=message.message,
            snapshot=snapshot,
        )
    except (TypeError, ValueError) as error:
        raise BridgeProtocolError(f"Invalid operation response: {error}") from error


def bridge_event(message: common_pb2.BridgeEvent) -> BridgeEvent:
    if not message.HasField("snapshot"):
        raise BridgeProtocolError("Bridge event has no snapshot")
    try:
        event_type = _EVENT_TYPES[message.type]
    except KeyError as error:
        raise BridgeProtocolError(
            f"Unsupported Bridge event type: {message.type}"
        ) from error
    try:
        return BridgeEvent(
            session_id=message.session_id,
            event_sequence=message.event_sequence,
            type=event_type,
            snapshot=timer_snapshot(message.snapshot),
            description=message.description,
        )
    except (TypeError, ValueError) as error:
        raise BridgeProtocolError(f"Invalid Bridge event: {error}") from error


def serialize(message: Message) -> bytes:
    return message.SerializeToString()
