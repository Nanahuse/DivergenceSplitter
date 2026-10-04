"""LiveSplit runtime data models and derived endpoint helpers."""

from dataclasses import dataclass
from enum import Enum, auto

from divergencesplitter.livesplit.models import LiveSplitConnection

BRIDGE_HOST = "127.0.0.1"
RPC_PATH = "/bridge/v2/rpc"
EVENTS_PATH = "/bridge/v2/events"


def rpc_endpoint(connection: LiveSplitConnection) -> str:
    """Return the Protocol v2 RPC WebSocket endpoint for one connection."""

    return f"ws://{BRIDGE_HOST}:{connection.port}{RPC_PATH}"


def event_endpoint(connection: LiveSplitConnection) -> str:
    """Return the Protocol v2 Events WebSocket endpoint for one connection."""

    return f"ws://{BRIDGE_HOST}:{connection.port}{EVENTS_PATH}"


class TimerPhase(Enum):
    NOT_RUNNING = auto()
    STARTING = auto()
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
    run_revision: int
    phase: TimerPhase
    split_index: int
    split_count: int

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "state_revision",
            "run_revision",
            "split_count",
        ):
            _require_non_negative_integer(name, getattr(self, name))
        if self.phase is TimerPhase.NOT_RUNNING:
            if self.split_index != -1:
                raise ValueError("NOT_RUNNING requires split_index == -1")
        elif self.phase is TimerPhase.STARTING:
            if self.split_count == 0 or not 0 <= self.split_index < self.split_count:
                raise ValueError("STARTING requires 0 <= split_index < split_count")
        elif self.phase in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            if not 0 <= self.split_index < self.split_count:
                raise ValueError(
                    "RUNNING and PAUSED require 0 <= split_index < split_count"
                )
        elif self.split_count == 0 or self.split_index != self.split_count:
            raise ValueError("ENDED requires split_index == split_count > 0")


@dataclass(frozen=True)
class LiveSplitSegmentInfo:
    index: int
    name: str

    def __post_init__(self) -> None:
        _require_non_negative_integer("index", self.index)


@dataclass(frozen=True)
class LiveSplitRunInfo:
    session_id: int
    run_revision: int
    segments: tuple[LiveSplitSegmentInfo, ...]

    def __post_init__(self) -> None:
        _require_non_negative_integer("session_id", self.session_id)
        _require_non_negative_integer("run_revision", self.run_revision)


class LiveSplitUpdateKind(Enum):
    INITIAL = auto()
    RESYNC = auto()
    PERIODIC = auto()
    TRANSITION = auto()


class LiveSplitResyncReason(Enum):
    GAP = auto()
    SESSION_CHANGED = auto()
    CONNECTION_LOST = auto()
    UPDATE_QUEUE_OVERFLOW = auto()
    EVENT_INBOX_OVERFLOW = auto()


@dataclass(frozen=True)
class LiveSplitUpdate:
    kind: LiveSplitUpdateKind
    snapshot: LiveSplitSnapshot
    run_info: LiveSplitRunInfo | None = None
