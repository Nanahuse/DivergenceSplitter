"""LiveSplit runtime state models and endpoint helpers."""

from dataclasses import dataclass
from enum import Enum, auto

from divergencesplitter.livesplit.models import LiveSplitConnection

BRIDGE_HOST = "127.0.0.1"
RPC_PATH = "/bridge/v3/rpc"
EVENTS_PATH = "/bridge/v3/events"


def rpc_endpoint(connection: LiveSplitConnection) -> str:
    """Return the Protocol v3 RPC WebSocket endpoint for one connection."""

    return f"ws://{BRIDGE_HOST}:{connection.port}{RPC_PATH}"


def event_endpoint(connection: LiveSplitConnection) -> str:
    """Return the Protocol v3 Events WebSocket endpoint for one connection."""

    return f"ws://{BRIDGE_HOST}:{connection.port}{EVENTS_PATH}"


class TimerPhase(Enum):
    NOT_RUNNING = auto()
    RUNNING = auto()
    PAUSED = auto()
    ENDED = auto()


@dataclass(frozen=True)
class LiveSplitSnapshot:
    """Timer-only state; connection and update ordering live on LiveSplitUpdate."""

    phase: TimerPhase
    split_index: int
    split_count: int

    def __post_init__(self) -> None:
        if self.split_count < 0:
            raise ValueError("split_count must be non-negative")
        if self.phase is TimerPhase.NOT_RUNNING:
            if self.split_index != -1:
                raise ValueError("NOT_RUNNING requires split_index == -1")
        elif self.phase in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            if not 0 <= self.split_index < self.split_count:
                raise ValueError("RUNNING and PAUSED require a valid split_index")
        elif self.split_count == 0 or self.split_index != self.split_count:
            raise ValueError("ENDED requires split_index == split_count > 0")


@dataclass(frozen=True)
class LiveSplitSegmentInfo:
    index: int
    name: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be non-negative")


@dataclass(frozen=True)
class LiveSplitRunInfo:
    """Run metadata needed by the runtime and its status display."""

    game_name: str = ""
    category_name: str = ""
    segments: tuple[LiveSplitSegmentInfo, ...] = ()

    @property
    def structure(self) -> tuple[str, str, tuple[tuple[int, str], ...]]:
        return (
            self.game_name,
            self.category_name,
            tuple((segment.index, segment.name) for segment in self.segments),
        )


class LiveSplitUpdateKind(Enum):
    INITIAL = auto()
    RESYNC = auto()
    PERIODIC = auto()
    TRANSITION = auto()
    RUN_CHANGED = auto()


class LiveSplitResyncReason(Enum):
    GAP = auto()
    SESSION_CHANGED = auto()
    CONNECTION_LOST = auto()
    UPDATE_QUEUE_OVERFLOW = auto()
    EVENT_INBOX_OVERFLOW = auto()


@dataclass(frozen=True)
class LiveSplitUpdate:
    """A locally accepted update with its Bridge connection/event context."""

    kind: LiveSplitUpdateKind
    snapshot: LiveSplitSnapshot
    run_info: LiveSplitRunInfo | None = None
    session_id: int = 1
    event_sequence: int | None = None
    state_epoch: int = 0
    run_structure_changed: bool = False
