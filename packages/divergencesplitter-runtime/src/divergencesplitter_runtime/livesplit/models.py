"""LiveSplit runtime data models."""

from dataclasses import dataclass
from enum import Enum, auto


class TimerPhase(Enum):
    NOT_RUNNING = auto()
    RUNNING = auto()
    PAUSED = auto()
    ENDED = auto()


def _require_non_negative_integer(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class LiveSplitSnapshot:
    session_id: int
    state_revision: int
    event_sequence: int
    phase: TimerPhase
    split_index: int
    split_count: int

    def __post_init__(self) -> None:
        for name in ("session_id", "state_revision", "event_sequence", "split_count"):
            _require_non_negative_integer(name, getattr(self, name))
        if self.phase is TimerPhase.NOT_RUNNING:
            if self.split_index != -1:
                raise ValueError("NOT_RUNNING requires split_index == -1")
        elif self.phase in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            if not 0 <= self.split_index < self.split_count:
                raise ValueError(
                    "RUNNING and PAUSED require 0 <= split_index < split_count"
                )
        elif self.split_count == 0 or self.split_index != self.split_count:
            raise ValueError("ENDED requires split_index == split_count > 0")


class LiveSplitUpdateKind(Enum):
    INITIAL = auto()
    RESYNC = auto()
    PERIODIC = auto()
    TRANSITION = auto()


@dataclass(frozen=True)
class LiveSplitUpdate:
    kind: LiveSplitUpdateKind
    snapshot: LiveSplitSnapshot
