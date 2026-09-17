"""Monitor snapshot acquisition shared by every Monitor panel.

One coordinator owns the single ``take_condition_observations`` consume per
update cycle, so no two panels can steal each other's snapshot. It retains the
latest observations that actually arrived (an empty poll never clears the
display) and caches throughput/latency metrics at a slower cadence, letting the
Monitor update task poll at observation rate without rebuilding every value.
"""

from __future__ import annotations

from dataclasses import dataclass

from divergencesplitter_runtime.instance_runtime import InstanceStatus
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    DetectorTreeSnapshot,
    InstanceRunSnapshot,
)

from divergencesplitter_ui.presentation import MonotonicClock, SystemMonotonicClock
from divergencesplitter_ui.session import SessionController, SessionState, is_active

DEFAULT_METRICS_INTERVAL_NS = 1_000_000_000


@dataclass(frozen=True)
class MonitorSnapshot:
    """One consistent read of everything the Monitor displays."""

    state: SessionState
    tree: DetectorTreeSnapshot | None
    instance_statuses: tuple[InstanceStatus, ...]
    run_infos: tuple[InstanceRunSnapshot, ...]
    observations: tuple[ConditionObservation, ...]
    metrics: RuntimeMetricsSnapshot | None


class MonitorUpdateCoordinator:
    """Read a Monitor snapshot from the controller and its diagnostics.

    ``take_condition_observations`` is a consuming API: the coordinator calls it
    exactly once per ``snapshot`` and keeps the latest non-empty result, so a
    later consumer (for example a diagnostics view) can take over the same
    snapshot without a second read.
    """

    def __init__(
        self,
        controller: SessionController,
        *,
        metrics_interval_ns: int = DEFAULT_METRICS_INTERVAL_NS,
        clock: MonotonicClock | None = None,
    ) -> None:
        self._controller = controller
        self._metrics_interval_ns = metrics_interval_ns
        self._clock = clock if clock is not None else SystemMonotonicClock()
        self._bound_diagnostics: object | None = None
        self._observations: tuple[ConditionObservation, ...] = ()
        self._metrics: RuntimeMetricsSnapshot | None = None
        self._last_metrics_ns: int | None = None

    def snapshot(self) -> MonitorSnapshot:
        """Read one snapshot, consuming fresh observations at most once."""

        state = self._controller.state
        diagnostics = self._controller.diagnostics
        if diagnostics is None:
            self._reset()
            return MonitorSnapshot(state, None, (), (), (), None)
        if diagnostics is not self._bound_diagnostics:
            # A new session owns new diagnostics; drop the previous session's
            # retained observations and metrics so no stale card survives.
            self._reset()
            self._bound_diagnostics = diagnostics

        taken = diagnostics.take_condition_observations()
        if taken:
            self._observations = taken
        if not is_active(state):
            # Once the session is no longer active nothing is currently being
            # evaluated, so the last active path must not linger in the display.
            self._observations = ()

        now = self._clock.now_ns()
        if (
            self._last_metrics_ns is None
            or now - self._last_metrics_ns >= self._metrics_interval_ns
        ):
            self._metrics = diagnostics.metrics_snapshot()
            self._last_metrics_ns = now

        return MonitorSnapshot(
            state=state,
            tree=diagnostics.detector_tree(),
            instance_statuses=diagnostics.instance_statuses(),
            run_infos=diagnostics.instance_run_infos(),
            observations=self._observations,
            metrics=self._metrics,
        )

    def _reset(self) -> None:
        self._bound_diagnostics = None
        self._observations = ()
        self._metrics = None
        self._last_metrics_ns = None
