from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TimerPhase(Enum):
    NOT_RUNNING = "not_running"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ENDED = "ended"


class TimerOperation(Enum):
    START = "start"
    SPLIT = "split"
    SKIP = "skip"
    UNDO = "undo"
    RESET = "reset"
    PAUSE = "pause"
    RESUME = "resume"


class BridgeEventType(Enum):
    TIMER_STARTED = "timer_started"
    TIMER_SPLIT = "timer_split"
    TIMER_SKIPPED = "timer_skipped"
    TIMER_UNDO = "timer_undo"
    TIMER_RESET = "timer_reset"
    TIMER_PAUSED = "timer_paused"
    TIMER_RESUMED = "timer_resumed"
    GAME_TIME_INITIALIZED = "game_time_initialized"
    GAME_TIME_SET = "game_time_set"
    GAME_TIME_PAUSED = "game_time_paused"
    GAME_TIME_RESUMED = "game_time_resumed"
    RUN_CHANGED = "run_changed"
    STATE_SNAPSHOT = "state_snapshot"


def _require_non_negative(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class TimerSnapshot:
    state_revision: int
    session_id: int
    event_sequence: int
    phase: TimerPhase
    split_index: int
    split_count: int
    real_time_ticks: int | None
    game_time_ticks: int | None
    is_paused: bool
    is_game_time_initialized: bool

    def __post_init__(self) -> None:
        for name in ("state_revision", "session_id", "event_sequence", "split_count"):
            _require_non_negative(name, getattr(self, name))
        if not isinstance(self.phase, TimerPhase):
            raise TypeError("phase must be a TimerPhase")
        if isinstance(self.split_index, bool) or not isinstance(self.split_index, int):
            raise TypeError("split_index must be an integer")
        if self.split_index < -1:
            raise ValueError("split_index must be at least -1")
        for name in ("real_time_ticks", "game_time_ticks"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise TypeError(f"{name} must be an integer or None")
        if not isinstance(self.is_paused, bool):
            raise TypeError("is_paused must be a bool")
        if not isinstance(self.is_game_time_initialized, bool):
            raise TypeError("is_game_time_initialized must be a bool")


@dataclass(frozen=True)
class AttachResult:
    session_id: int
    snapshot: TimerSnapshot

    def __post_init__(self) -> None:
        _require_non_negative("session_id", self.session_id)
        if self.session_id != self.snapshot.session_id:
            raise ValueError("attach session_id must match snapshot session_id")


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str
    snapshot: TimerSnapshot | None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("success must be a bool")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        if self.success and self.snapshot is None:
            raise ValueError("a successful operation must include a snapshot")


@dataclass(frozen=True)
class BridgeEvent:
    session_id: int
    event_sequence: int
    type: BridgeEventType
    snapshot: TimerSnapshot
    description: str

    def __post_init__(self) -> None:
        _require_non_negative("session_id", self.session_id)
        _require_non_negative("event_sequence", self.event_sequence)
        if not isinstance(self.type, BridgeEventType):
            raise TypeError("type must be a BridgeEventType")
        if self.session_id != self.snapshot.session_id:
            raise ValueError("event session_id must match snapshot session_id")
        if self.event_sequence != self.snapshot.event_sequence:
            raise ValueError("event_sequence must match snapshot event_sequence")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
