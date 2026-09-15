"""Immutable runtime metric values exposed to status consumers."""

from dataclasses import dataclass

from divergencesplitter import MonotonicTime


@dataclass(frozen=True)
class InstanceEvaluationMetrics:
    """One scenario instance's evaluation latency over the latest window.

    Both values are integer nanoseconds, or ``None`` when the current window
    holds no evaluation sample (not ready, just connected, or idle).
    """

    scenario_index: int
    average_latency_ns: int | None
    max_latency_ns: int | None


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
