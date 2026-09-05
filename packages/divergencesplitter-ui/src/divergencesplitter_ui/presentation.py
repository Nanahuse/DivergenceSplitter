"""Pure presentation and update logic for the main screen.

Nothing in this module imports Dear PyGui. It decides *what* to update from
session state, observation snapshots, and a monotonic clock, leaving *how* to
reach the widgets to the renderer. The decision points below are the units
covered by behavior tests:

* state re-rendering only on change,
* observation re-rendering only when a new snapshot arrives,
* a ~10 Hz image cadence and a 1 Hz fps cadence,
* joining tree nodes to observations by object identity, and
* status/score formatting including ``SKIPPED`` and unobserved conditions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from divergencesplitter import ConditionStatus, Frame
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot
from divergencesplitter_runtime.observability import (
    ConditionNode,
    ConditionObservation,
    DetectorTreeSnapshot,
    ScenarioNode,
)

UNOBSERVED_LABEL = "UNOBSERVED"

_STATUS_LABELS = {
    ConditionStatus.TRUE: "TRUE",
    ConditionStatus.FALSE: "FALSE",
    ConditionStatus.SKIPPED: "SKIPPED",
}


class ObservableDiagnostics(Protocol):
    """The read-only runtime view consumed by the screen."""

    def take_latest_input_frame(self) -> Frame | None: ...

    def take_condition_observations(self) -> tuple[ConditionObservation, ...]: ...

    def detector_tree(self) -> DetectorTreeSnapshot | None: ...

    def metrics_snapshot(self) -> RuntimeMetricsSnapshot: ...


class MonotonicClock(Protocol):
    """Provide monotonic nanoseconds for display update scheduling."""

    def now_ns(self) -> int: ...


class SystemMonotonicClock:
    """Read the process monotonic clock."""

    def now_ns(self) -> int:
        return time.monotonic_ns()


def status_label(status: ConditionStatus | None) -> str:
    """Return the display label for a condition status."""

    if status is None:
        return UNOBSERVED_LABEL
    return _STATUS_LABELS[status]


def format_score(value: float | None) -> str:
    """Format a detector score for display, or an empty string for ``None``."""

    if value is None:
        return ""
    return f"{value:.4g}"


def has_new_observations(observations: tuple[ConditionObservation, ...]) -> bool:
    """Return whether ``observations`` carries a fresh snapshot to apply.

    ``take_condition_observations`` clears the pending snapshot, so a non-empty
    tuple means new values arrived and the renderer must repaint; an empty one
    means the previous frame has already been represented.
    """

    return bool(observations)


class ObservationIndex:
    """Join display-tree nodes to observations by condition object identity."""

    def __init__(self, observations: tuple[ConditionObservation, ...]) -> None:
        self._by_id = {id(item.condition): item for item in observations}

    @classmethod
    def build(cls, observations: tuple[ConditionObservation, ...]) -> ObservationIndex:
        return cls(observations)

    def get(self, node: ConditionNode) -> ConditionObservation | None:
        return self._by_id.get(id(node.condition))


@dataclass(frozen=True)
class ConditionView:
    """Transfer-only display values for one condition node."""

    condition_type: str
    detector_type: str | None
    status_label: str
    minimum_score: float | None
    latest_score: float | None
    max_score: float | None


def view_for(node: ConditionNode, index: ObservationIndex) -> ConditionView:
    """Resolve one condition node to its display values.

    ``node.detector`` carries the ``Detected``-specific threshold and reference
    images while the observation (joined by identity) carries the latest status
    and scores. Distinct ``Detected`` conditions sharing one detector resolve to
    their own observations and never borrow another's scores.
    """

    observation = index.get(node)
    minimum_score = node.detector.minimum_score if node.detector is not None else None
    return ConditionView(
        condition_type=node.condition_type,
        detector_type=(
            node.detector.detector_type if node.detector is not None else None
        ),
        status_label=status_label(
            observation.status if observation is not None else None
        ),
        minimum_score=minimum_score,
        latest_score=observation.latest_score if observation is not None else None,
        max_score=observation.max_score if observation is not None else None,
    )


def condition_label(view: ConditionView) -> str:
    """Format one Condition node label."""

    return f"{view.condition_type} [{view.status_label}]"


def scenario_label(node: ScenarioNode) -> str:
    """Format a Scenario node with its LiveSplit destination."""

    connection = node.connection
    return (
        f"Scenario {node.scenario_index}"
        f"  rpc={connection.rpc_endpoint}  event={connection.event_endpoint}"
    )


def detector_label(view: ConditionView) -> str | None:
    """Format one Detector node label, including all score values."""

    if view.detector_type is None:
        return None
    threshold = format_score(view.minimum_score) or "—"
    latest = format_score(view.latest_score) or "—"
    maximum = format_score(view.max_score) or "—"
    return (
        f"{view.detector_type} [{view.status_label}]"
        f"  threshold={threshold}  current={latest}  max={maximum}"
    )


class ScreenPresenter:
    """Own the update cadences and change detection for one screen."""

    def __init__(
        self,
        *,
        image_interval_ns: int = 100_000_000,
        fps_interval_ns: int = 1_000_000_000,
        clock: MonotonicClock | None = None,
    ) -> None:
        self._image_interval_ns = image_interval_ns
        self._fps_interval_ns = fps_interval_ns
        self._clock = clock if clock is not None else SystemMonotonicClock()
        self._last_image_ns: int | None = None
        self._last_fps_ns: int | None = None
        self._last_state: object = _UNSET

    def image_due(self) -> bool:
        now = self._clock.now_ns()
        if (
            self._last_image_ns is None
            or now - self._last_image_ns >= self._image_interval_ns
        ):
            self._last_image_ns = now
            return True
        return False

    def fps_due(self) -> bool:
        now = self._clock.now_ns()
        if (
            self._last_fps_ns is None
            or now - self._last_fps_ns >= self._fps_interval_ns
        ):
            self._last_fps_ns = now
            return True
        return False

    def state_changed(self, state: object) -> bool:
        if state is self._last_state:
            return False
        self._last_state = state
        return True


class ExpansionEvent(Enum):
    """Texture lifecycle decision for a detector node's reference images."""

    SHOW = auto()
    HIDE = auto()
    NONE = auto()


class ExpansionState:
    """Track which detector nodes have their reference images expanded.

    Reference images are only materialized (``SHOW``) the first time a node is
    opened and are released (``HIDE``) when it is collapsed. Both operations are
    idempotent and nodes without reference images never materialize anything.
    """

    def __init__(self) -> None:
        self._expanded: set[int | str] = set()

    def is_expanded(self, key: int | str) -> bool:
        return key in self._expanded

    def reconcile(
        self,
        key: int | str,
        *,
        expanded: bool,
        has_reference_images: bool,
    ) -> ExpansionEvent:
        if not has_reference_images:
            if key in self._expanded:
                self._expanded.discard(key)
                return ExpansionEvent.HIDE
            return ExpansionEvent.NONE
        if expanded:
            if key in self._expanded:
                return ExpansionEvent.NONE
            self._expanded.add(key)
            return ExpansionEvent.SHOW
        if key in self._expanded:
            self._expanded.discard(key)
            return ExpansionEvent.HIDE
        return ExpansionEvent.NONE


_UNSET = object()
