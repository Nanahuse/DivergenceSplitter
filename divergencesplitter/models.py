"""Data models shared by frame sources and image detectors.

``Frame`` intentionally holds only the NumPy image array. Array copy and
ownership rules are guaranteed by each frame source implementation. Detector
configuration values remain hashable so equivalent detectors can share cache
entries.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np

Pixel = int | float
ConfigImage = Sequence[Sequence[Pixel]]
ImageArray = np.ndarray


@dataclass(frozen=True, order=True)
class MonotonicTime:
    """A point on the monotonic clock as raw nanoseconds."""

    nanoseconds: int


@dataclass(frozen=True)
class Frame:
    """A single captured frame carrying only its image array."""

    image: ImageArray


@dataclass
class FrameContext:
    frame: Frame
    now: MonotonicTime
    preprocessing_cache: dict[object, object] = field(default_factory=dict)
    detection_cache: dict[object, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionResult:
    """Data model holding the numeric observation of a single detector run.

    ``score`` is a required detector-specific measure with no cross-detector
    meaning.
    """

    score: float


class TimerPhase(Enum):
    """LiveSplit timer phase observed in a snapshot."""

    UNSPECIFIED = auto()
    NOT_RUNNING = auto()
    STARTING = auto()
    RUNNING = auto()
    PAUSED = auto()
    ENDED = auto()


class TimerOperation(Enum):
    """LiveSplit operation a fired rule requests."""

    START = auto()
    SPLIT = auto()
    SKIP = auto()
    UNDO = auto()
    RESET = auto()
    PAUSE = auto()
    RESUME = auto()


@dataclass(frozen=True)
class LiveSplitSnapshot:
    """Frozen observation of a single LiveSplit target.

    ``state_revision``, ``session_id``, ``event_sequence`` and ``split_count``
    are non-negative counters. ``split_index`` may be ``-1`` because the Bridge
    reports it before the first split, so it is not range-validated.
    """

    target_id: str
    state_revision: int
    session_id: int
    event_sequence: int
    phase: TimerPhase
    split_index: int
    split_count: int
    is_fresh: bool

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("target_id must not be empty")
        if self.state_revision < 0:
            raise ValueError(
                f"state_revision must be non-negative: {self.state_revision}"
            )
        if self.session_id < 0:
            raise ValueError(f"session_id must be non-negative: {self.session_id}")
        if self.event_sequence < 0:
            raise ValueError(
                f"event_sequence must be non-negative: {self.event_sequence}"
            )
        if self.split_count < 0:
            raise ValueError(f"split_count must be non-negative: {self.split_count}")


@dataclass(frozen=True)
class ActionCandidate:
    """Frozen decision from a fired rule, pending arbiter selection."""

    scenario_id: str
    target_id: str
    operation: TimerOperation
    rule_id: str
    priority: int
    expected_snapshot: LiveSplitSnapshot

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must not be empty")
        if not self.target_id:
            raise ValueError("target_id must not be empty")
        if not self.rule_id:
            raise ValueError("rule_id must not be empty")
        if self.target_id != self.expected_snapshot.target_id:
            raise ValueError(
                f"target_id {self.target_id!r} does not match "
                f"expected_snapshot.target_id {self.expected_snapshot.target_id!r}"
            )
