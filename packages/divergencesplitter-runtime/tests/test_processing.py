import threading

import numpy as np
from divergencesplitter import Action, Frame, MonotonicTime
from divergencesplitter.clock import TimeProvider
from divergencesplitter_runtime import (
    ActionSubmission,
    LatestFrameBuffer,
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
        self.contexts: list[object] = []

    @property
    def current_snapshot(self) -> LiveSplitSnapshot | None:
        return self._fake_snapshot

    def apply_livesplit_update(self, update: LiveSplitUpdate) -> None:
        self.updates.append(update)
        self._fake_snapshot = update.snapshot

    def evaluate(self, context: object) -> Action | None:
        self.contexts.append(context)
        return self.action


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
        self, action: Action, expected_snapshot: LiveSplitSnapshot
    ) -> ActionSubmission:
        self.requests.append((action, expected_snapshot))
        return ActionSubmission.ACCEPTED


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.frames: list[tuple[Frame, MonotonicTime]] = []
        self.errors: list[tuple[int, Exception]] = []
        self.frame_started = threading.Event()

    def frame_processing_started(
        self, frame: Frame, processing_started_at: MonotonicTime
    ) -> None:
        self.frames.append((frame, processing_started_at))
        self.frame_started.set()

    def scenario_evaluation_failed(self, scenario_index: int, error: Exception) -> None:
        self.errors.append((scenario_index, error))


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
        (scenario,),
        (worker,),
        buffer,
        diagnostics=diagnostics,
        time_provider=clock,
    )

    process_one_frame(runtime, diagnostics)

    assert scenario.updates == [initial]
    assert worker.requests == [(Action("split"), initial.snapshot)]
    assert clock.calls == 1
    assert diagnostics.frames == [(pending_frame, MonotonicTime(20))]


def test_all_scenarios_share_one_context_and_one_clock_read() -> None:
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
        (first, second),
        (first_worker, second_worker),
        buffer,
        diagnostics=diagnostics,
        time_provider=clock,
    )

    process_one_frame(runtime, diagnostics)

    assert first.contexts[0] is second.contexts[0]
    assert clock.calls == 1


def test_unavailable_worker_applies_updates_but_skips_evaluation() -> None:
    initial = LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())
    scenario = FakeScenarioRuntime(Action("split"))
    worker = FakeWorker((initial,))
    worker._fake_available = False
    buffer = LatestFrameBuffer()
    buffer.publish(frame())
    diagnostics = RecordingDiagnostics()
    runtime = ProcessingRuntime(
        (scenario,),
        (worker,),
        buffer,
        diagnostics=diagnostics,
        time_provider=FakeTimeProvider(),
    )

    process_one_frame(runtime, diagnostics)

    assert scenario.updates == [initial]
    assert scenario.contexts == []
    assert worker.requests == []
