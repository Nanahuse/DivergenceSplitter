"""Pure presentation and update logic for the main screen.

This module is GUI-independent. It decides *what* to update from session state,
observation snapshots, and a monotonic clock, leaving *how* to reach the widgets
to the GUI layer. The decision points below are the units covered by behavior
tests:

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
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.livesplit.models import LiveSplitRunInfo
from divergencesplitter_runtime.metrics import (
    InstanceEvaluationMetrics,
    RuntimeMetricsSnapshot,
)
from divergencesplitter_runtime.observability import (
    ConditionNode,
    ConditionObservation,
    DetectorTreeSnapshot,
    InstanceRunSnapshot,
    ScenarioNode,
)

UNOBSERVED_LABEL = "UNOBSERVED"

_STATUS_LABELS = {
    ConditionStatus.TRUE: "TRUE",
    ConditionStatus.FALSE: "FALSE",
    ConditionStatus.SKIPPED: "SKIPPED",
    ConditionStatus.ERROR: "ERROR",
}


class ObservableDiagnostics(Protocol):
    """The read-only runtime view consumed by the screen."""

    def take_latest_input_frame(self) -> Frame | None: ...

    def take_latest_processed_frame(self) -> Frame | None: ...

    def take_condition_observations(self) -> tuple[ConditionObservation, ...]: ...

    def detector_tree(self) -> DetectorTreeSnapshot | None: ...

    def instance_statuses(self) -> tuple[InstanceStatus, ...]: ...

    def instance_run_infos(self) -> tuple[InstanceRunSnapshot, ...]: ...

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
        return "—"
    return f"{value:.4f}"


def format_latency_ms(value_ns: int | None) -> str:
    """Format an evaluation latency in milliseconds, or ``—`` when unmeasured."""

    if value_ns is None:
        return "—"
    return f"{value_ns / 1_000_000:.1f} ms"


def evaluation_latency_label(metrics: InstanceEvaluationMetrics) -> str:
    """Format one scenario's evaluation Ave / Max display line."""

    return (
        f"Scenario {metrics.scenario_index + 1}:  "
        f"Ave {format_latency_ms(metrics.average_latency_ns)}  "
        f"Max {format_latency_ms(metrics.max_latency_ns)}"
    )


UNMEASURED_FPS = "— fps"


@dataclass(frozen=True)
class GlobalStatusText:
    """Transfer-only display values for the Global Status panel."""

    state: str
    input_fps: str
    processing_fps: str


def format_fps(value: float) -> str:
    """Format one throughput value in frames per second."""

    return f"{value:.1f} fps"


def global_status_text(
    state: object,
    snapshot: RuntimeMetricsSnapshot | None,
) -> GlobalStatusText:
    """Format the session state and throughput metrics for the Global Status.

    ``state`` is any object exposing a ``name`` (the ``SessionState`` enum);
    ``snapshot`` is ``None`` before a session publishes metrics, which renders
    as an unmeasured placeholder rather than a stale value.
    """

    return GlobalStatusText(
        state=getattr(state, "name", str(state)),
        input_fps=(
            UNMEASURED_FPS if snapshot is None else format_fps(snapshot.input_fps)
        ),
        processing_fps=(
            UNMEASURED_FPS if snapshot is None else format_fps(snapshot.processing_fps)
        ),
    )


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

    active: bool = False
    duration_nanoseconds: int | None = None
    elapsed_nanoseconds: int | None = None
    progress_current: float | int | None = None
    progress_target: float | int | None = None
    progress_unit: str | None = None


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
        active=observation.active if observation is not None else False,
        duration_nanoseconds=node.duration_nanoseconds,
        elapsed_nanoseconds=(
            observation.elapsed_nanoseconds if observation is not None else None
        ),
        progress_current=(
            observation.progress_current if observation is not None else None
        ),
        progress_target=(
            observation.progress_target if observation is not None else None
        ),
        progress_unit=observation.progress_unit if observation is not None else None,
    )


def condition_label(view: ConditionView) -> str:
    """Format one Condition node label."""

    marker = "▶ " if view.active else ""
    active = "  ACTIVE" if view.active else ""
    progress = ""
    if view.progress_unit == "score":
        current = format_score(view.progress_current)
        target = format_score(view.progress_target)
        progress = f"  {current} / {target}"
    elif view.progress_unit == "count":
        progress = f"  {view.progress_current} / {view.progress_target}"
    elif view.progress_unit == "step":
        progress = f"  step {view.progress_current} / {view.progress_target}"
    if view.duration_nanoseconds is not None:
        elapsed = (
            "—"
            if view.elapsed_nanoseconds is None
            else f"{view.elapsed_nanoseconds / 1_000_000_000:.3f} s"
        )
        progress = f"  {elapsed} / {view.duration_nanoseconds / 1_000_000_000:.3f} s"
    return f"{marker}{view.condition_type} [{view.status_label}]{progress}{active}"


_INSTANCE_STATE_LABELS = {
    InstanceRuntimeState.CONNECTING: "Connecting...",
    InstanceRuntimeState.READY: "Connected",
    InstanceRuntimeState.FAILED: "Failed",
    InstanceRuntimeState.STOPPED: "Stopped",
}


def instance_state_label(state: InstanceRuntimeState) -> str:
    """Return the short display label for one instance lifecycle state."""

    return _INSTANCE_STATE_LABELS[state]


def _format_seconds(value_nanoseconds: float | None) -> str:
    if value_nanoseconds is None:
        return "—"
    return f"{value_nanoseconds / 1_000_000_000:.3f} s"


def _format_progress_value(value: float | None) -> str:
    return "—" if value is None else str(value)


def condition_progress_label(view: ConditionView) -> str:
    """Format one condition's current progress for the Scenario Overview.

    Detected conditions render ``current / threshold   Max: max`` and prefix
    ``ERROR`` when evaluation failed. Elapsed and Hold render seconds, Nth a
    count, and Then a step. Conditions without progress render an empty string.
    """

    if view.progress_unit == "score":
        detail = (
            f"{format_score(view.latest_score)} / {format_score(view.minimum_score)}"
            f"   Max: {format_score(view.max_score)}"
        )
        if view.status_label == "ERROR":
            return f"ERROR   {detail}"
        return detail
    if view.progress_unit == "nanoseconds":
        return (
            f"{_format_seconds(view.progress_current)} / "
            f"{_format_seconds(view.progress_target)}"
        )
    if view.progress_unit == "count":
        return (
            f"{_format_progress_value(view.progress_current)} / "
            f"{_format_progress_value(view.progress_target)}"
        )
    if view.progress_unit == "step":
        return (
            f"step {_format_progress_value(view.progress_current)} / "
            f"{_format_progress_value(view.progress_target)}"
        )
    return ""


def instance_status_label(status: InstanceStatus) -> str:
    label = instance_state_label(status.state)
    return f"{label} — {status.error}" if status.error else label


def split_label(split_index: int, run_info: LiveSplitRunInfo | None) -> str:
    """Format a Split node base label with the LiveSplit Segment name.

    The Segment is matched by its authoritative ``index`` field, so a Run whose
    segment order differs from the scenario still resolves correctly. A missing
    Segment, an empty name, or no Run at all all fall back to ``Split N``.
    """

    base = f"Split {split_index}"
    if run_info is None:
        return base
    name = next(
        (segment.name for segment in run_info.segments if segment.index == split_index),
        None,
    )
    if not name:
        return base
    return f"{base} — {name}"


def scenario_label(node: ScenarioNode) -> str:
    """Format a Scenario node with its LiveSplit destination."""

    connection = node.connection
    return (
        f"Scenario {node.scenario_index}"
        f"  rpc={connection.rpc_endpoint}  event={connection.event_endpoint}"
    )


def detector_label(view: ConditionView) -> str | None:
    """Format the stable Detector node label; scores are separate fields."""

    if view.detector_type is None:
        return None
    marker = "▶ " if view.active else ""
    active = "  ACTIVE" if view.active else ""
    return f"{marker}{view.detector_type} [{view.status_label}]{active}"


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
