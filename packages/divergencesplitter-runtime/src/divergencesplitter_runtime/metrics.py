"""Immutable runtime metric values exposed to status consumers."""

from dataclasses import dataclass

from divergencesplitter import MonotonicTime


@dataclass(frozen=True)
class RuntimeMetricsSnapshot:
    """A point-in-time copy of runtime throughput metrics."""

    sampled_at: MonotonicTime
    window_seconds: float
    input_fps: float
    processing_fps: float
    input_frames_total: int
    processed_frames_total: int
