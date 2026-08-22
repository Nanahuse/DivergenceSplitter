"""Data models shared by frame sources and image detectors.

``Frame`` intentionally holds only the NumPy image array. Array copy and
ownership rules are guaranteed by each frame source implementation. Detector
configuration values remain hashable so equivalent detectors can share cache
entries.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from divergencesplitter.rule.action import Action
    from divergencesplitter.rule.interface import Condition

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
    NOT_RUNNING = auto()
    RUNNING = auto()
    PAUSED = auto()
    ENDED = auto()


def _require_non_negative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class LiveSplitSnapshot:
    target_id: str
    session_id: int
    state_revision: int
    event_sequence: int
    phase: TimerPhase
    split_index: int
    split_count: int

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("target_id must not be empty")
        for name in ("session_id", "state_revision", "event_sequence", "split_count"):
            _require_non_negative_integer(name, getattr(self, name))
        if not isinstance(self.phase, TimerPhase):
            raise TypeError("phase must be a supported TimerPhase")
        if isinstance(self.split_index, bool) or not isinstance(self.split_index, int):
            raise TypeError("split_index must be an integer")
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

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LiveSplitUpdateKind):
            raise TypeError("kind must be a supported LiveSplitUpdateKind")
        if not isinstance(self.snapshot, LiveSplitSnapshot):
            raise TypeError("snapshot must be a LiveSplitSnapshot")


def _source_location() -> tuple[str, int]:
    try:
        caller = inspect.currentframe()
        for _ in range(3):
            caller = caller.f_back if caller is not None else None
        if caller is None:
            return "<unknown>", 0
        filename = caller.f_code.co_filename
        line = caller.f_lineno
        path = Path(filename)
        if not path.is_absolute():
            return filename, line
        resolved = path.resolve()
        for parent in (resolved.parent, *resolved.parents):
            if (parent / ".git").exists():
                return resolved.relative_to(parent).as_posix(), line
        return str(path), line
    except AttributeError, OSError, RuntimeError, ValueError:
        return "<unknown>", 0


@dataclass(frozen=True)
class RuleDefinition:
    action: Action
    condition_factory: Callable[[], Condition]
    name: str | None = field(default=None, compare=False)
    source_path: str = field(init=False, compare=False)
    source_line: int = field(init=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self.condition_factory):
            raise TypeError("condition_factory must be callable")
        if self.name == "":
            object.__setattr__(self, "name", None)
        source_path, source_line = _source_location()
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "source_line", source_line)


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    target_id: str
    rules: Mapping[int, tuple[RuleDefinition, ...]]

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must not be empty")
        if not self.target_id:
            raise ValueError("target_id must not be empty")
        copied: dict[int, tuple[RuleDefinition, ...]] = {}
        for split_index, definitions in self.rules.items():
            if (
                isinstance(split_index, bool)
                or not isinstance(split_index, int)
                or split_index < 0
            ):
                raise ValueError("split keys must be non-negative integers")
            immutable_definitions = tuple(definitions)
            if not all(
                isinstance(definition, RuleDefinition)
                for definition in immutable_definitions
            ):
                raise ValueError("rules must contain RuleDefinition values")
            copied[split_index] = immutable_definitions
        object.__setattr__(self, "rules", MappingProxyType(copied))
