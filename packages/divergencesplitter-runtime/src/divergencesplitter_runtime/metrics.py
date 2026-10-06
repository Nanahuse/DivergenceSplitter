"""Immutable runtime metric values exposed to status consumers."""

from dataclasses import dataclass

from divergencesplitter import MonotonicTime


@dataclass(frozen=True)
class InstanceEvaluationMetrics:
    """One scenario instance's evaluation CPU duration over the latest window.

    Both values are integer nanoseconds of thread CPU time spent inside
    ``runtime.evaluate()``, or ``None`` when the current window holds no
    evaluation sample (not ready, just connected, or idle). Wall-clock time the
    thread was stopped is deliberately excluded.
    """

    scenario_index: int
    average_duration_ns: int | None
    max_duration_ns: int | None


@dataclass(frozen=True)
class RuntimeMetricsSnapshot:
    """A point-in-time copy of runtime throughput metrics."""

    sampled_at: MonotonicTime
    window_seconds: float
    input_fps: float
    processing_fps: float
    input_frames_total: int
    processed_frames_total: int
    instance_evaluations: tuple[InstanceEvaluationMetrics, ...] = ()
