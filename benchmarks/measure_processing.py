"""Measure the finite-buffer processing path at a 60 fps input cadence."""

from __future__ import annotations

import argparse
import platform
import threading
import time
import tracemalloc

import numpy as np
from divergencesplitter import (
    ColorRangeConfig,
    ColorRangeDetector,
    DifferenceHashSimilarityConfig,
    DifferenceHashSimilarityDetector,
    Frame,
    FrameContext,
    MeanBrightnessDetector,
    MonotonicTime,
    TemplateMatchConfig,
    TemplateMatchDetector,
    evaluate,
)
from divergencesplitter.detector.models import freeze_config_image
from divergencesplitter_runtime import LatestFrameBuffer, PublishResult

INPUT_FPS = 60.0
FRAME_INTERVAL_NS = round(1_000_000_000 / INPUT_FPS)


class _Measurements:
    def __init__(self) -> None:
        self.published = 0
        self.processed = 0
        self.overwritten = 0
        self.capture_to_completed_ns: list[int] = []
        self.detector_ns: list[int] = []
        self.cache_hit_ns: list[int] = []
        self.detector_samples: dict[str, list[int]] = {}


def _percentile(values: list[int], percentile: float) -> float:
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return ordered[index] / 1_000_000


def _run_case(width: int, height: int, duration_seconds: float) -> None:
    image = np.random.default_rng(0).integers(
        0,
        256,
        size=(height, width, 3),
        dtype=np.uint8,
    )
    reference = freeze_config_image(image[:64, :64].tolist())
    detectors = (
        MeanBrightnessDetector(),
        ColorRangeDetector(ColorRangeConfig((0, 0, 0), (255, 255, 255))),
        DifferenceHashSimilarityDetector(DifferenceHashSimilarityConfig(reference)),
        TemplateMatchDetector(TemplateMatchConfig(reference)),
    )
    buffer = LatestFrameBuffer()
    measurements = _Measurements()
    frame_count = round(duration_seconds * INPUT_FPS)

    def capture() -> None:
        started_at = time.monotonic_ns()
        for index in range(frame_count):
            deadline = started_at + index * FRAME_INTERVAL_NS
            remaining = deadline - time.monotonic_ns()
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000)
            frame = Frame(image, MonotonicTime(time.monotonic_ns()))
            result = buffer.publish(frame)
            measurements.published += 1
            if result is PublishResult.OVERWROTE:
                measurements.overwritten += 1
        buffer.stop()

    def process() -> None:
        while (frame := buffer.take()) is not None:
            context = FrameContext(frame, MonotonicTime(time.monotonic_ns()))
            detector_started_at = time.monotonic_ns()
            for detector in detectors:
                started_at = time.monotonic_ns()
                evaluate(context, detector)
                completed_at = time.monotonic_ns()
                measurements.detector_samples.setdefault(
                    type(detector).__name__, []
                ).append(completed_at - started_at)
            detector_completed_at = time.monotonic_ns()
            evaluate(context, detectors[0])
            cache_hit_completed_at = time.monotonic_ns()
            measurements.processed += 1
            measurements.detector_ns.append(detector_completed_at - detector_started_at)
            measurements.cache_hit_ns.append(
                cache_hit_completed_at - detector_completed_at
            )
            measurements.capture_to_completed_ns.append(
                cache_hit_completed_at - frame.captured_at.nanoseconds
            )

    tracemalloc.start()
    started_at = time.monotonic()
    processing_thread = threading.Thread(target=process, name="benchmark-processing")
    capture_thread = threading.Thread(target=capture, name="benchmark-capture")
    processing_thread.start()
    capture_thread.start()
    capture_thread.join()
    processing_thread.join()
    elapsed = time.monotonic() - started_at
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    detector_fields = "".join(
        f" detector.{name}.p95_ms={_percentile(samples, 0.95):.3f}"
        for name, samples in measurements.detector_samples.items()
    )
    print(
        "benchmark.processing"
        f" resolution={width}x{height}"
        f" input_fps={measurements.published / elapsed:.2f}"
        f" processing_fps={measurements.processed / elapsed:.2f}"
        f" published={measurements.published}"
        f" processed={measurements.processed}"
        f" overwritten={measurements.overwritten}"
        " capture_to_completed_p95_ms="
        f"{_percentile(measurements.capture_to_completed_ns, 0.95):.3f}"
        f" detectors_p95_ms={_percentile(measurements.detector_ns, 0.95):.3f}"
        f" cache_hit_p95_ms={_percentile(measurements.cache_hit_ns, 0.95):.3f}"
        f" peak_traced_mib={peak_bytes / 1024 / 1024:.3f}"
        f"{detector_fields}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    arguments = parser.parse_args()
    print(
        "benchmark.environment"
        f" python={platform.python_version()}"
        f" platform={platform.platform()}"
        f" duration_seconds={arguments.duration}"
        f" target_input_fps={INPUT_FPS}"
        " scenario=four_builtin_detectors"
        " bridge=not_measured"
    )
    for width, height in ((640, 360), (1280, 720)):
        _run_case(width, height, arguments.duration)


if __name__ == "__main__":
    main()
