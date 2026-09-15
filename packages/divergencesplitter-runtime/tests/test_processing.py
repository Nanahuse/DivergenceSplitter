import threading
import time
from collections.abc import Callable
from typing import cast

import numpy as np
from divergencesplitter import (
    Action,
    ClipRegion,
    DetectionResult,
    Frame,
    FrameContext,
    FrameNormalizationError,
    FrameNormalizer,
    MonotonicTime,
    OutputSize,
    evaluate,
)
from divergencesplitter.clock import TimeProvider
from divergencesplitter.scenario.models import Scenario
from divergencesplitter_runtime import (
    ActionSubmission,
    InstanceRuntime,
    InstanceRuntimeState,
    LatestFrameBuffer,
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    ProcessingRuntime,
    ScenarioRuntime,
    TimerPhase,
)
from divergencesplitter_runtime.livesplit import BridgeWorker


def snapshot() -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=1,
        state_revision=0,
        event_sequence=0,
        run_revision=1,
        phase=TimerPhase.RUNNING,
        split_index=0,
        split_count=1,
    )


def frame(captured_at: int = 10) -> Frame:
    return Frame(
        image=np.zeros((1, 1), dtype=np.uint8),
        captured_at=MonotonicTime(captured_at),
    )


class FakeTimeProvider(TimeProvider):
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> MonotonicTime:
        self.calls += 1
        return MonotonicTime(20)


class FakeScenarioRuntime(ScenarioRuntime):
    def __init__(self, action: Action | None = None) -> None:
        self.action = action
        self._fake_snapshot: LiveSplitSnapshot | None = None
        self.updates: list[LiveSplitUpdate] = []
        self.contexts: list[FrameContext] = []

    @property
    def current_snapshot(self) -> LiveSplitSnapshot | None:
        return self._fake_snapshot

    def apply_livesplit_update(self, update: LiveSplitUpdate) -> None:
        self.updates.append(update)
        self._fake_snapshot = update.snapshot

    def evaluate(self, context: FrameContext) -> Action | None:
        self.contexts.append(context)
        return self.action


class CountingDetector:
    def __init__(self) -> None:
        self.detections = 0

    @property
    def reference_images(self) -> tuple:
        return ()

    def detect(self, context: FrameContext) -> DetectionResult:
        self.detections += 1
        return DetectionResult(score=0.0)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CountingDetector)

    def __hash__(self) -> int:
        return hash("CountingDetector")


class DetectingScenarioRuntime(FakeScenarioRuntime):
    def __init__(self, detector: CountingDetector) -> None:
        super().__init__()
        self.detector = detector

    def evaluate(self, context: FrameContext) -> Action | None:
        self.contexts.append(context)
        evaluate(context, self.detector)
        return None


class FakeWorker(BridgeWorker):
    def __init__(self, updates: tuple[LiveSplitUpdate, ...]) -> None:
        self._fake_updates = updates
        self._fake_available = True
        self.requests: list[tuple[Action, LiveSplitSnapshot]] = []

    @property
    def is_available(self) -> bool:
        return self._fake_available

    def drain_updates(self) -> tuple[LiveSplitUpdate, ...]:
        updates = self._fake_updates
        self._fake_updates = ()
        return updates

    def submit_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
        *,
        generation: int | None = None,
    ) -> ActionSubmission:
        self.requests.append((action, expected_snapshot))
        return ActionSubmission.ACCEPTED


class SignalingBuffer(LatestFrameBuffer):
    def __init__(self) -> None:
        super().__init__()
        self.take_started = threading.Event()

    def take(self, timeout_seconds: float | None = None) -> Frame | None:
        self.take_started.set()
        return super().take(timeout_seconds)


class RecordingNormalizer(FrameNormalizer):
    def __init__(
        self,
        *,
        clip_region: ClipRegion | None = None,
        output_size: OutputSize | None = None,
    ) -> None:
        super().__init__(clip_region=clip_region, output_size=output_size)
        self.frames: list[Frame] = []

    def normalize(self, frame: Frame) -> Frame | FrameNormalizationError:
        self.frames.append(frame)
        return super().normalize(frame)


class ProcessingInstance(InstanceRuntime):
    """Prepared instance double; lifecycle is covered in test_instance_runtime."""

    @property
    def state(self) -> InstanceRuntimeState:
        return InstanceRuntimeState.READY

    def process_updates(self) -> None:
        assert self.scenario_runtime is not None
        for update in self.worker.drain_updates():
            self.scenario_runtime.apply_livesplit_update(update)


def instance(scenario: ScenarioRuntime, worker: BridgeWorker) -> InstanceRuntime:
    result = ProcessingInstance(cast(Scenario, None), worker)
    result.scenario_runtime = scenario
    return result


def make_run(revision: int = 1, name: str = "A") -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=1,
        run_revision=revision,
        segments=(LiveSplitSegmentInfo(0, name),),
    )


class RunScriptInstance(ProcessingInstance):
    """Emit a scripted sequence of Runs from successive process_updates calls."""

    def __init__(self, runs: list[LiveSplitRunInfo | None]) -> None:
        super().__init__(cast(Scenario, None), FakeWorker(()))
        self.scenario_runtime = FakeScenarioRuntime()
        self._scripted_runs = runs

    def process_updates(self) -> None:
        self.run_info = self._scripted_runs.pop(0)


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.frames: list[tuple[Frame, MonotonicTime]] = []
        self.errors: list[tuple[int, Exception]] = []
        self.frame_started = threading.Event()
        self.normalization_errors: list[FrameNormalizationError] = []
        self.normalization_failed = threading.Event()
        self.run_changes: list[tuple[int, LiveSplitRunInfo | None]] = []

    def frame_processing_started(
        self, frame: Frame, processing_started_at: MonotonicTime
    ) -> None:
        self.frames.append((frame, processing_started_at))
        self.frame_started.set()

    def frame_normalization_failed(self, error: FrameNormalizationError) -> None:
        self.normalization_errors.append(error)
        self.normalization_failed.set()

    def frame_processing_completed(self, context: FrameContext) -> None:
        pass

    def scenario_evaluation_failed(self, scenario_index: int, error: Exception) -> None:
        self.errors.append((scenario_index, error))

    def instance_run_changed(
        self,
        scenario_index: int,
        run_info: LiveSplitRunInfo | None,
    ) -> None:
        self.run_changes.append((scenario_index, run_info))


def process_one_frame(
    runtime: ProcessingRuntime,
    diagnostics: RecordingDiagnostics,
) -> None:
    thread = threading.Thread(target=runtime.run)
    thread.start()
    assert diagnostics.frame_started.wait(1)
    runtime.request_stop()
    thread.join(1)
    assert not thread.is_alive()


def test_applies_updates_before_evaluation_and_submits_action_with_snapshot() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    scenario = FakeScenarioRuntime(Action("split"))
    worker = FakeWorker((initial,))
    buffer = LatestFrameBuffer()
    pending_frame = frame()
    buffer.publish(pending_frame)
    clock = FakeTimeProvider()
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance(scenario, worker),),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=clock,
    )

    process_one_frame(runtime, diagnostics)

    assert scenario.updates == [initial]
    assert worker.requests == [(Action("split"), initial.snapshot)]
    assert clock.calls == 1
    assert diagnostics.frames == [(pending_frame, MonotonicTime(20))]


def test_all_scenarios_share_one_frame_evaluation_and_one_clock_read() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    first = FakeScenarioRuntime()
    second = FakeScenarioRuntime()
    first_worker = FakeWorker((initial,))
    second_worker = FakeWorker((initial,))
    buffer = LatestFrameBuffer()
    buffer.publish(frame())
    clock = FakeTimeProvider()
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance(first, first_worker), instance(second, second_worker)),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=clock,
    )

    process_one_frame(runtime, diagnostics)

    first_context = first.contexts[0]
    second_context = second.contexts[0]
    assert first_context is not second_context
    assert first_context.shared is second_context.shared
    assert first_context.frame is second_context.frame
    assert first_context.now == second_context.now
    assert first_context.evaluated_condition_ids is not (
        second_context.evaluated_condition_ids
    )
    assert clock.calls == 1


def test_equivalent_detectors_are_evaluated_once_across_scenarios() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    first_detector = CountingDetector()
    second_detector = CountingDetector()
    first = DetectingScenarioRuntime(first_detector)
    second = DetectingScenarioRuntime(second_detector)
    buffer = LatestFrameBuffer()
    buffer.publish(frame())
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (
            instance(first, FakeWorker((initial,))),
            instance(second, FakeWorker((initial,))),
        ),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )

    process_one_frame(runtime, diagnostics)

    assert first_detector.detections + second_detector.detections == 1


def test_unavailable_worker_applies_updates_but_skips_evaluation() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    scenario = FakeScenarioRuntime(Action("split"))
    worker = FakeWorker((initial,))
    worker._fake_available = False
    buffer = LatestFrameBuffer()
    buffer.publish(frame())
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance(scenario, worker),),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )

    process_one_frame(runtime, diagnostics)

    assert scenario.updates == [initial]
    assert scenario.contexts == []
    assert worker.requests == []


def wait_for(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


def test_applies_bridge_updates_while_waiting_for_frames() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    scenario = FakeScenarioRuntime()
    worker = FakeWorker((initial,))
    buffer = SignalingBuffer()
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance(scenario, worker),),
        buffer,
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )
    thread = threading.Thread(target=runtime.run)
    thread.start()
    assert buffer.take_started.wait(1)

    # Bridge updates are drained even while no frame is available, but the
    # scenario is not evaluated until one arrives.
    wait_for(lambda: scenario.updates == [initial])
    assert scenario.contexts == []

    buffer.publish(frame())
    assert diagnostics.frame_started.wait(1)
    runtime.request_stop()
    thread.join(1)

    assert not thread.is_alive()
    assert scenario.updates == [initial]
    assert len(scenario.contexts) == 1


def test_normalizes_frame_once_before_scenario_evaluation() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    scenario = FakeScenarioRuntime()
    worker = FakeWorker((initial,))
    buffer = LatestFrameBuffer()
    pending_frame = Frame(
        image=np.arange(16, dtype=np.uint8).reshape((4, 4)),
        captured_at=MonotonicTime(10),
    )
    buffer.publish(pending_frame)
    diagnostics = RecordingDiagnostics()
    normalizer = RecordingNormalizer(
        clip_region=ClipRegion(x=1, y=1, width=2, height=2),
        output_size=OutputSize(width=1, height=1),
    )
    runtime = ProcessingRuntime(
        (instance(scenario, worker),),
        buffer,
        normalizer,
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )

    process_one_frame(runtime, diagnostics)

    evaluated = scenario.contexts[0].frame
    assert normalizer.frames == [pending_frame]
    assert evaluated.image.shape == (1, 1)
    assert evaluated.captured_at == pending_frame.captured_at
    assert diagnostics.frames == [(pending_frame, MonotonicTime(20))]


def run_detection_runtime(
    instances: tuple[InstanceRuntime, ...],
) -> tuple[ProcessingRuntime, RecordingDiagnostics]:
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        instances,
        LatestFrameBuffer(),
        FrameNormalizer(),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )
    return runtime, diagnostics


def test_run_info_initial_acquisition_notifies_once() -> None:
    run = make_run()
    runtime, diagnostics = run_detection_runtime((RunScriptInstance([run, run]),))

    runtime._apply_bridge_updates()
    assert diagnostics.run_changes == [(0, run)]

    runtime._apply_bridge_updates()
    assert diagnostics.run_changes == [(0, run)]


def test_run_info_change_notifies_new_revision() -> None:
    first = make_run(revision=1)
    second = make_run(revision=2, name="B")
    runtime, diagnostics = run_detection_runtime((RunScriptInstance([first, second]),))

    runtime._apply_bridge_updates()
    runtime._apply_bridge_updates()

    assert diagnostics.run_changes == [(0, first), (0, second)]


def test_run_info_disconnect_notifies_none() -> None:
    run = make_run()
    runtime, diagnostics = run_detection_runtime((RunScriptInstance([run, None]),))

    runtime._apply_bridge_updates()
    runtime._apply_bridge_updates()

    assert diagnostics.run_changes == [(0, run), (0, None)]


def test_run_info_reconnect_notifies_latest_run() -> None:
    first = make_run(revision=1)
    reconnected = make_run(revision=5, name="Reconnected")
    runtime, diagnostics = run_detection_runtime(
        (RunScriptInstance([first, None, reconnected]),)
    )

    for _ in range(3):
        runtime._apply_bridge_updates()

    assert diagnostics.run_changes == [(0, first), (0, None), (0, reconnected)]


def test_run_info_notifications_are_scoped_per_scenario() -> None:
    first = make_run(name="A")
    second = make_run(name="B")
    runtime, diagnostics = run_detection_runtime(
        (RunScriptInstance([first]), RunScriptInstance([second]))
    )

    runtime._apply_bridge_updates()

    assert diagnostics.run_changes == [(0, first), (1, second)]


def test_normalization_error_stops_processing_without_evaluating_scenario() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    scenario = FakeScenarioRuntime()
    worker = FakeWorker((initial,))
    buffer = LatestFrameBuffer()
    buffer.publish(frame())
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (instance(scenario, worker),),
        buffer,
        FrameNormalizer(clip_region=ClipRegion(x=0, y=0, width=2, height=2)),
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )
    thread = threading.Thread(target=runtime.run)

    thread.start()
    assert diagnostics.normalization_failed.wait(1)
    thread.join(1)

    assert not thread.is_alive()
    assert scenario.contexts == []
    assert len(diagnostics.normalization_errors) == 1
    assert buffer.take() is None
