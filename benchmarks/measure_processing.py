"""Baseline benchmark for the current scenario evaluation runtime.

The benchmark drives the production runtime path instead of evaluating
detectors directly: a synthetic 60 fps frame source feeds a
``LatestFrameBuffer`` through ``ProcessingRuntime``, which normalizes each
frame once and publishes a ``SharedFrameEvaluation`` to every scenario
instance. Each instance owns a thread and evaluates its scenario through
``ScenarioRuntime``; detectors are reached through ``Detected`` conditions and
per-instance latency is observed through ``OperationalDiagnostics``.

A deterministic in-memory bridge stub replaces LiveSplit, so no network, RPC,
or ZeroMQ work is measured. The runtime itself is never modified; all timing
and accounting lives in the instrumentation below.

Output is one machine-comparable line per case plus one line per detector:

    benchmark.runtime resolution=... instances=... conditions=... logging=...
    benchmark.detector detector=... p95_ms=...
"""

from __future__ import annotations

import argparse
import io
import logging
import math
import platform
import threading
import time
import tracemalloc
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self, TextIO, cast
from unittest.mock import patch

import numpy as np
from divergencesplitter import (
    Action,
    ColorRangeConfig,
    ColorRangeDetector,
    Detected,
    DifferenceHashSimilarityConfig,
    DifferenceHashSimilarityDetector,
    Elapsed,
    ErrorAction,
    Frame,
    FrameContext,
    FrameNormalizer,
    FrameSourceError,
    FrameSourceState,
    ImageDetector,
    LiveSplitConnection,
    MeanAbsoluteSimilarityConfig,
    MeanAbsoluteSimilarityDetector,
    MeanBrightnessDetector,
    MonotonicTime,
    PhaseCorrelationConfig,
    PhaseCorrelationDetector,
    Region,
    RootMeanSquareSimilarityConfig,
    RootMeanSquareSimilarityDetector,
    Rule,
    Scenario,
    TemplateMatchConfig,
    TemplateMatchDetector,
)
from divergencesplitter.detector.models import FrozenConfigImage, freeze_config_image
from divergencesplitter_runtime import (
    ApplicationRuntime,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    OperationalDiagnostics,
    PublishResult,
    ScenarioInstance,
    TimerPhase,
)

INPUT_FPS = 60.0
REFERENCE_SIZE = 64
ALPHA_OPAQUE_MARGIN = 16
DEFAULT_DURATION_SECONDS = 5.0
LOG_LEVELS = {"DEBUG": logging.DEBUG, "OFF": logging.CRITICAL + 1}
_ACTION_OPERATION = "split"
_IMPOSSIBLE_MINIMUM_SCORE = 2.0
_NEVER_ELAPSED_NANOSECONDS = 10**15


@dataclass(frozen=True)
class _Case:
    """One runtime benchmark configuration.

    ``kind`` selects the evaluated scenario shape: ``detectors`` runs the
    heavyweight detector suite, while ``conditions`` runs one cheap detector
    plus enough lightweight conditions to reach ``conditions`` rules so the
    condition-tree and observation cost is measurable in isolation.
    """

    width: int
    height: int
    instances: int
    conditions: int
    logging: str
    kind: str = "detectors"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


QUICK_CASES = (
    _Case(640, 360, instances=1, conditions=10, logging="OFF"),
    _Case(640, 360, instances=2, conditions=10, logging="OFF"),
    _Case(1280, 720, instances=1, conditions=10, logging="OFF"),
    _Case(1280, 720, instances=2, conditions=10, logging="OFF"),
    _Case(1280, 720, instances=2, conditions=10, logging="DEBUG"),
    _Case(1280, 720, instances=2, conditions=10, logging="OFF", kind="conditions"),
    _Case(1280, 720, instances=2, conditions=100, logging="OFF", kind="conditions"),
    _Case(1280, 720, instances=2, conditions=500, logging="OFF", kind="conditions"),
    _Case(1280, 720, instances=2, conditions=500, logging="DEBUG", kind="conditions"),
)

FULL_CASES = tuple(
    _Case(w, h, instances=i, conditions=10, logging=lvl, kind="detectors")
    for w, h in ((640, 360), (1280, 720))
    for i in (1, 2)
    for lvl in ("OFF", "DEBUG")
) + tuple(
    _Case(w, h, instances=i, conditions=c, logging=lvl, kind="conditions")
    for w, h in ((640, 360), (1280, 720))
    for i in (1, 2)
    for c in (10, 100, 500)
    for lvl in ("OFF", "DEBUG")
)


class _DiscardStream(io.TextIOBase):
    """Writable sink that keeps only a byte count.

    DEBUG logging still builds and formats every record; only the terminal
    write is discarded so the benchmark does not measure console or disk I/O.
    """

    def __init__(self) -> None:
        super().__init__()
        self.bytes_written = 0

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.bytes_written += len(text)
        return len(text)

    def flush(self) -> None:
        return None


class _SyntheticFrameSource:
    """A deterministic, real-time paced frame source (60 fps by default)."""

    def __init__(self, image: np.ndarray, fps: float = INPUT_FPS) -> None:
        self._image = image
        self._interval_ns = round(1_000_000_000 / fps)
        self._normalizer = FrameNormalizer()
        self._state = FrameSourceState.NOT_READY
        self._next_ns: int | None = None

    @property
    def state(self) -> FrameSourceState:
        return self._state

    @property
    def normalizer(self) -> FrameNormalizer:
        return self._normalizer

    def prepare(self) -> None:
        self._state = FrameSourceState.READY
        if self._next_ns is None:
            self._next_ns = time.monotonic_ns()

    def read(self) -> Frame:
        if self._next_ns is None:
            self._next_ns = time.monotonic_ns()
        now = time.monotonic_ns()
        if self._next_ns > now:
            time.sleep((self._next_ns - now) / 1_000_000_000)
        self._next_ns += self._interval_ns
        return Frame(
            image=self._image,
            captured_at=MonotonicTime(time.monotonic_ns()),
        )

    def handle_error(self, error: FrameSourceError) -> ErrorAction:
        return ErrorAction.STOP

    def close(self) -> None:
        self._state = FrameSourceState.NOT_READY

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class _DetectorRecorder:
    """Per-instance detector accounting; touched only by its instance thread."""

    def __init__(self) -> None:
        self.samples: dict[str, list[int]] = {}
        self.computations: dict[str, int] = {}
        self.lookups: dict[str, int] = {}

    def record_compute(self, label: str, duration_ns: int) -> None:
        self.samples.setdefault(label, []).append(duration_ns)
        self.computations[label] = self.computations.get(label, 0) + 1

    def record_lookup(self, label: str) -> None:
        self.lookups[label] = self.lookups.get(label, 0) + 1


class _TimedDetector:
    """Detector proxy that records real compute time and delegates all else.

    It hashes and compares equal to its wrapped detector, so equivalent
    definitions still share one cached ``DetectionResult`` per frame.
    """

    def __init__(
        self,
        label: str,
        detector: ImageDetector,
        recorder: _DetectorRecorder,
    ) -> None:
        self._label = label
        self._detector = detector
        self._recorder = recorder

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._detector, name)

    def detect(self, context: FrameContext) -> Any:
        started_at = time.perf_counter_ns()
        try:
            return self._detector.detect(context)
        finally:
            self._recorder.record_compute(
                self._label,
                time.perf_counter_ns() - started_at,
            )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _TimedDetector):
            return self._detector == other._detector
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._detector)


class _CountingDetected(Detected):
    """``Detected`` that also counts cache lookups before delegating."""

    def __init__(
        self,
        label: str,
        detector: ImageDetector,
        recorder: _DetectorRecorder,
    ) -> None:
        super().__init__(detector, _IMPOSSIBLE_MINIMUM_SCORE)
        self._label = label
        self._recorder = recorder

    def _evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: bool,
    ) -> bool | None:
        if not is_short_circuited:
            self._recorder.record_lookup(self._label)
        return super()._evaluate(context, is_short_circuited=is_short_circuited)


class _BenchmarkDiagnostics(OperationalDiagnostics):
    """Operational diagnostics plus raw per-instance benchmark samples."""

    def __init__(self, stream: _DiscardStream, *, level: int) -> None:
        super().__init__(cast("TextIO", stream), level=level)
        self._lock = threading.Lock()
        self.published = 0
        self.overwritten = 0
        self.processed = 0
        self.first_captured_ns: int | None = None
        self.last_captured_ns: int | None = None
        self.evaluated_counts: dict[int, int] = {}
        self.first_eval_ns: dict[int, int] = {}
        self.last_eval_ns: dict[int, int] = {}
        self.latencies_ns: dict[int, list[int]] = {}
        self.detection_entries_max = 0
        self.preprocessing_entries_max = 0

    def frame_received(self, frame: Frame, publish_result: PublishResult) -> None:
        captured = frame.captured_at.nanoseconds
        with self._lock:
            self.published += 1
            if self.first_captured_ns is None:
                self.first_captured_ns = captured
            self.last_captured_ns = captured
            if publish_result is PublishResult.OVERWROTE:
                self.overwritten += 1
        super().frame_received(frame, publish_result)

    def frame_processing_completed(self, context: FrameContext) -> None:
        with self._lock:
            self.processed += 1
        super().frame_processing_completed(context)

    def instance_evaluated(
        self,
        scenario_index: int,
        context: FrameContext,
        completed_at: MonotonicTime,
        evaluation_cpu_duration_ns: int,
        evaluation_wall_duration_ns: int,
    ) -> None:
        completed = completed_at.nanoseconds
        latency = evaluation_cpu_duration_ns
        with self._lock:
            self.evaluated_counts[scenario_index] = (
                self.evaluated_counts.get(scenario_index, 0) + 1
            )
            if scenario_index not in self.first_eval_ns:
                self.first_eval_ns[scenario_index] = completed
            self.last_eval_ns[scenario_index] = completed
            self.latencies_ns.setdefault(scenario_index, []).append(latency)
            self.detection_entries_max = max(
                self.detection_entries_max,
                context.cache.detection_count(),
            )
            self.preprocessing_entries_max = max(
                self.preprocessing_entries_max,
                context.cache.preprocessing_count(),
            )
        super().instance_evaluated(
            scenario_index,
            context,
            completed_at,
            evaluation_cpu_duration_ns,
            evaluation_wall_duration_ns,
        )


class _StubSubscriber:
    """Bridge SUB double that never produces an event."""

    def __init__(self, event_endpoint: str = "", **_: object) -> None:
        self._closed = threading.Event()

    def receive(self, *, timeout_ms: int | None = None) -> None:
        self._closed.wait(0.0 if timeout_ms is None else timeout_ms / 1000)

    def close(self) -> None:
        self._closed.set()


def _stub_adapter_type(update: LiveSplitUpdate) -> type:
    """Build an adapter class returning one fixed authoritative snapshot."""

    class _StubBridgeAdapter:
        def __init__(
            self,
            connection: LiveSplitConnection,
            diagnostics: object = None,
            rpc_timeout_ms: int = 3000,
            **_: object,
        ) -> None:
            del connection, diagnostics, rpc_timeout_ms

        def attach(self) -> LiveSplitUpdate:
            return update

        def handle_event(self, event: object) -> object:
            return event

        def execute_action(
            self,
            action: Action,
            expected: LiveSplitSnapshot,
        ) -> object:
            raise RuntimeError("benchmark bridge stub must not dispatch actions")

        def resync(self, reason: object) -> LiveSplitUpdate:
            del reason
            return update

        def close(self) -> None:
            return None

    return _StubBridgeAdapter


def _reference_images() -> tuple[FrozenConfigImage, FrozenConfigImage]:
    rng = np.random.default_rng(1)
    reference = rng.integers(
        0,
        256,
        size=(REFERENCE_SIZE, REFERENCE_SIZE, 3),
        dtype=np.uint8,
    )
    frozen = freeze_config_image(reference.tolist())
    alpha = np.zeros((REFERENCE_SIZE, REFERENCE_SIZE, 4), dtype=np.uint8)
    alpha[:, :, :3] = reference
    alpha[
        ALPHA_OPAQUE_MARGIN : REFERENCE_SIZE - ALPHA_OPAQUE_MARGIN,
        ALPHA_OPAQUE_MARGIN : REFERENCE_SIZE - ALPHA_OPAQUE_MARGIN,
        3,
    ] = 255
    frozen_alpha = freeze_config_image(alpha.tolist())
    return frozen, frozen_alpha


def _detector_definitions(
    width: int,
    height: int,
    recorder: _DetectorRecorder,
) -> tuple[tuple[str, _TimedDetector], ...]:
    reference, alpha_reference = _reference_images()
    roi = Region(0, 0, REFERENCE_SIZE, REFERENCE_SIZE)
    template_roi = Region(100, 100, width - 164, height - 164)
    inner: tuple[tuple[str, ImageDetector], ...] = (
        ("mean_brightness", MeanBrightnessDetector()),
        (
            "color_range",
            ColorRangeDetector(ColorRangeConfig((0, 0, 0), (255, 255, 255))),
        ),
        (
            "difference_hash",
            DifferenceHashSimilarityDetector(DifferenceHashSimilarityConfig(reference)),
        ),
        ("template_full", TemplateMatchDetector(TemplateMatchConfig(reference))),
        (
            "template_roi",
            TemplateMatchDetector(TemplateMatchConfig(reference, template_roi)),
        ),
        (
            "mean_absolute_opaque",
            MeanAbsoluteSimilarityDetector(
                MeanAbsoluteSimilarityConfig(reference, roi)
            ),
        ),
        (
            "mean_absolute_alpha",
            MeanAbsoluteSimilarityDetector(
                MeanAbsoluteSimilarityConfig(alpha_reference, roi)
            ),
        ),
        (
            "root_mean_square_opaque",
            RootMeanSquareSimilarityDetector(
                RootMeanSquareSimilarityConfig(reference, roi)
            ),
        ),
        (
            "root_mean_square_alpha",
            RootMeanSquareSimilarityDetector(
                RootMeanSquareSimilarityConfig(alpha_reference, roi)
            ),
        ),
        (
            "phase_correlation",
            PhaseCorrelationDetector(PhaseCorrelationConfig(reference, roi)),
        ),
    )
    return tuple(
        (label, _TimedDetector(label, detector, recorder)) for label, detector in inner
    )


def _build_scenario(case: _Case, recorder: _DetectorRecorder) -> Scenario:
    if case.kind == "detectors":
        rules = [
            Rule(
                _CountingDetected(label, detector, recorder),
                Action(_ACTION_OPERATION),
            )
            for label, detector in _detector_definitions(
                case.width,
                case.height,
                recorder,
            )
        ]
    else:
        label = "mean_brightness"
        detector = _TimedDetector(label, MeanBrightnessDetector(), recorder)
        rules = [
            Rule(
                _CountingDetected(label, detector, recorder),
                Action(_ACTION_OPERATION),
            )
        ]
        rules.extend(
            Rule(
                Elapsed(_NEVER_ELAPSED_NANOSECONDS),
                Action(_ACTION_OPERATION),
            )
            for _ in range(max(0, case.conditions - 1))
        )
    return Scenario(
        start_condition=Elapsed(_NEVER_ELAPSED_NANOSECONDS),
        reset_condition=Elapsed(_NEVER_ELAPSED_NANOSECONDS),
        incomplete_condition=None,
        splits=(tuple(rules),),
    )


@dataclass(frozen=True)
class _CaseResult:
    diagnostics: _BenchmarkDiagnostics
    stream: _DiscardStream
    recorders: tuple[_DetectorRecorder, ...]
    elapsed_seconds: float
    peak_traced_bytes: int | None


def _execute_case(
    case: _Case,
    duration_seconds: float,
    *,
    memory_only: bool,
) -> _CaseResult:
    image = np.random.default_rng(0).integers(
        0,
        256,
        size=(case.height, case.width, 3),
        dtype=np.uint8,
    )
    source = _SyntheticFrameSource(image)
    recorders = tuple(_DetectorRecorder() for _ in range(case.instances))
    instances = tuple(
        ScenarioInstance(
            connection=LiveSplitConnection(
                f"benchmark-rpc-{index}",
                f"benchmark-event-{index}",
            ),
            scenario=_build_scenario(case, recorders[index]),
        )
        for index in range(case.instances)
    )
    stream = _DiscardStream()
    diagnostics = _BenchmarkDiagnostics(stream, level=LOG_LEVELS[case.logging])
    diagnostics.bind_runtime(instances, source)
    runtime = ApplicationRuntime(instances, source, diagnostics=diagnostics)

    split_count = max(1, len(instances[0].scenario.splits))
    snapshot = LiveSplitSnapshot(
        session_id=1,
        state_revision=0,
        event_sequence=0,
        run_revision=1,
        phase=TimerPhase.RUNNING,
        split_index=0,
        split_count=split_count,
    )
    update = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot)
    adapter_type = _stub_adapter_type(update)

    peak_traced_bytes: int | None = None
    if memory_only:
        tracemalloc.start()
    started_at = time.monotonic()
    timer = threading.Timer(duration_seconds, runtime.request_stop)
    timer.daemon = True
    timer.start()
    try:
        with (
            patch(
                "divergencesplitter_runtime.instance_runtime.LiveSplitBridgeAdapter",
                adapter_type,
            ),
            patch(
                "divergencesplitter_runtime.instance_runtime.BridgeEventSubscriber",
                _StubSubscriber,
            ),
        ):
            runtime.run()
    finally:
        timer.cancel()
        elapsed_seconds = time.monotonic() - started_at
        if memory_only:
            _, peak_traced_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        diagnostics.close()
    return _CaseResult(
        diagnostics,
        stream,
        recorders,
        elapsed_seconds,
        peak_traced_bytes,
    )


def _merge_recorders(
    recorders: tuple[_DetectorRecorder, ...],
) -> tuple[dict[str, list[int]], dict[str, int], dict[str, int]]:
    samples: dict[str, list[int]] = {}
    computations: dict[str, int] = {}
    lookups: dict[str, int] = {}
    for recorder in recorders:
        for label, values in recorder.samples.items():
            samples.setdefault(label, []).extend(values)
        for label, count in recorder.computations.items():
            computations[label] = computations.get(label, 0) + count
        for label, count in recorder.lookups.items():
            lookups[label] = lookups.get(label, 0) + count
    return samples, computations, lookups


def _percentile_ms(values: list[int], percentile: float) -> float:
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return ordered[index] / 1_000_000


def _span_fps(count: int, first_ns: int | None, last_ns: int | None) -> float:
    if count < 2 or first_ns is None or last_ns is None or last_ns <= first_ns:
        return 0.0
    return (count - 1) * 1_000_000_000 / (last_ns - first_ns)


def _format_runtime_line(case: _Case, result: _CaseResult) -> str:
    diagnostics = result.diagnostics
    _samples, computations, lookups = _merge_recorders(result.recorders)
    total_computations = sum(computations.values())
    total_lookups = sum(lookups.values())
    cache_hits = max(0, total_lookups - total_computations)
    hit_ratio = 0.0 if total_lookups == 0 else cache_hits / total_lookups
    evaluation_fps = [
        _span_fps(
            diagnostics.evaluated_counts.get(index, 0),
            diagnostics.first_eval_ns.get(index),
            diagnostics.last_eval_ns.get(index),
        )
        for index in range(case.instances)
    ]
    mean_evaluation_fps = (
        sum(evaluation_fps) / len(evaluation_fps) if evaluation_fps else 0.0
    )
    fields = [
        "benchmark.runtime",
        f"resolution={case.resolution}",
        f"instances={case.instances}",
        f"conditions={case.conditions}",
        f"logging={case.logging}",
        f"scenario={case.kind}",
        f"input_fps={_span_fps(diagnostics.published, diagnostics.first_captured_ns, diagnostics.last_captured_ns):.2f}",
        f"evaluation_fps={mean_evaluation_fps:.2f}",
        f"published={diagnostics.published}",
        f"processed={diagnostics.processed}",
        f"overwritten={diagnostics.overwritten}",
        f"elapsed_s={result.elapsed_seconds:.3f}",
    ]
    for index in range(case.instances):
        latencies = diagnostics.latencies_ns.get(index, [])
        fields.append(f"instance.{index}.evaluated={len(latencies)}")
        fields.append(f"instance.{index}.evaluation_fps={evaluation_fps[index]:.2f}")
        if latencies:
            fields.append(
                f"instance.{index}.p50_ms={_percentile_ms(latencies, 0.5):.3f}"
            )
            fields.append(
                f"instance.{index}.p95_ms={_percentile_ms(latencies, 0.95):.3f}"
            )
            fields.append(
                f"instance.{index}.max_ms={_percentile_ms(latencies, 1.0):.3f}"
            )
    fields.extend(
        (
            f"detector_lookups={total_lookups}",
            f"detector_computations={total_computations}",
            f"detector_cache_hits={cache_hits}",
            f"detector_cache_hit_ratio={hit_ratio:.3f}",
            f"detection_entries_max={diagnostics.detection_entries_max}",
            f"preprocessing_entries_max={diagnostics.preprocessing_entries_max}",
            f"log_bytes={result.stream.bytes_written}",
            "bridge=stub",
        )
    )
    return " ".join(fields)


def _format_detector_lines(case: _Case, result: _CaseResult) -> tuple[str, ...]:
    samples, computations, lookups = _merge_recorders(result.recorders)
    lines: list[str] = []
    for label in sorted(samples):
        values = samples[label]
        lines.append(
            "benchmark.detector"
            f" detector={label}"
            f" resolution={case.resolution}"
            f" instances={case.instances}"
            f" logging={case.logging}"
            f" lookups={lookups.get(label, 0)}"
            f" computations={computations.get(label, 0)}"
            f" p50_ms={_percentile_ms(values, 0.5):.3f}"
            f" p95_ms={_percentile_ms(values, 0.95):.3f}"
            f" max_ms={_percentile_ms(values, 1.0):.3f}"
        )
    return tuple(lines)


def _format_memory_line(case: _Case, result: _CaseResult) -> str:
    peak = result.peak_traced_bytes or 0
    return (
        "benchmark.memory"
        f" resolution={case.resolution}"
        f" instances={case.instances}"
        f" conditions={case.conditions}"
        f" logging={case.logging}"
        f" scenario={case.kind}"
        f" published={result.diagnostics.published}"
        f" processed={result.diagnostics.processed}"
        f" peak_traced_mib={peak / 1024 / 1024:.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--suite", choices=("quick", "full"), default="quick")
    parser.add_argument(
        "--memory",
        action="store_true",
        help="run each case under tracemalloc and report only peak memory",
    )
    arguments = parser.parse_args()
    if not math.isfinite(arguments.duration) or arguments.duration <= 0:
        parser.error("--duration must be a positive number")

    cases = QUICK_CASES if arguments.suite == "quick" else FULL_CASES
    print(
        "benchmark.environment"
        f" python={platform.python_version()}"
        f" platform={platform.platform()}"
        f" suite={arguments.suite}"
        f" duration_seconds={arguments.duration}"
        f" target_input_fps={INPUT_FPS}"
        " scenario=shared_frame_runtime"
        " bridge=stub"
    )
    for case in cases:
        result = _execute_case(case, arguments.duration, memory_only=arguments.memory)
        if arguments.memory:
            print(_format_memory_line(case, result))
            continue
        print(_format_runtime_line(case, result))
        for line in _format_detector_lines(case, result):
            print(line)


if __name__ == "__main__":
    main()
