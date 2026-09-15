"""Instance thread ownership: frames, events, actions, reconnect, isolation."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import cast

import numpy as np
from divergencesplitter import (
    Action,
    Detected,
    DetectionResult,
    Frame,
    FrameContext,
    LiveSplitConnection,
    MonotonicTime,
    ReferenceImage,
    Rule,
    Scenario,
)
from divergencesplitter.frame.models import SharedFrameEvaluation
from divergencesplitter_runtime import (
    ActionExecution,
    InstanceRuntime,
    InstanceRuntimeState,
    LiveSplitBridgeAdapter,
    LiveSplitResyncReason,
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)
from livesplit_bridge import BridgeConnectionLostError, common_pb2

# -- Deterministic test doubles ------------------------------------------------


class ScriptedSubscriber:
    """Blocking subscriber double consumed by the real BridgeEventReceiver."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._items: deque[object] = deque()
        self.closed = False

    def push(self, item: object) -> None:
        with self._condition:
            self._items.append(item)
            self._condition.notify_all()

    def receive(
        self, *, timeout_ms: int | None = None
    ) -> common_pb2.BridgeEvent | None:
        with self._condition:
            if not self._items:
                self._condition.wait(None if timeout_ms is None else timeout_ms / 1000)
            if not self._items:
                return None
            item = self._items.popleft()
        if isinstance(item, Exception):
            raise item
        return cast(common_pb2.BridgeEvent, item)

    def close(self) -> None:
        with self._condition:
            self.closed = True
            self._condition.notify_all()


class ScriptedAdapter:
    """Adapter double handling domain updates supplied by the subscriber."""

    def __init__(
        self,
        initial: LiveSplitUpdate,
        *,
        execute_result: ActionExecution = ActionExecution.DISPATCHED,
        log: list[str] | None = None,
    ) -> None:
        self.initial = initial
        self.baseline = initial.snapshot
        self.execute_result = execute_result
        self.handled: list[object] = []
        self.resynced: list[LiveSplitResyncReason] = []
        self.attempts: list[tuple[Action, LiveSplitSnapshot]] = []
        self.closed = False
        self.attached = 0
        self._log = log

    def attach(self) -> LiveSplitUpdate:
        self.attached += 1
        self.baseline = self.initial.snapshot
        return self.initial

    def handle_event(self, event: object) -> object:
        if self._log is not None:
            self._log.append("event")
        self.handled.append(event)
        if isinstance(event, Exception):
            raise event
        if isinstance(event, LiveSplitUpdate):
            self.baseline = event.snapshot
        return event

    def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
        self.resynced.append(reason)
        return LiveSplitUpdate(LiveSplitUpdateKind.RESYNC, self.baseline)

    def execute_action(
        self, action: Action, expected_snapshot: LiveSplitSnapshot
    ) -> ActionExecution:
        self.attempts.append((action, expected_snapshot))
        if (
            self.execute_result is ActionExecution.DISPATCHED
            and expected_snapshot != self.baseline
        ):
            return ActionExecution.NOT_DISPATCHED
        return self.execute_result

    def close(self) -> None:
        self.closed = True


class RecordingCondition:
    def __init__(
        self,
        result: bool,
        *,
        on_evaluate: Callable[[FrameContext], None] | None = None,
    ) -> None:
        self.result = result
        self._on_evaluate = on_evaluate
        self.calls = 0
        self.captured_at: list[int] = []

    @property
    def children(self) -> tuple:
        return ()

    def evaluate(
        self, context: FrameContext, *, is_short_circuited: bool = False
    ) -> bool:
        self.calls += 1
        self.captured_at.append(context.frame.captured_at.nanoseconds)
        if self._on_evaluate is not None:
            self._on_evaluate(context)
        return self.result

    def reset(self) -> None:
        pass


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.started: list[LiveSplitConnection] = []
        self.stopped: list[LiveSplitConnection] = []
        self.connection_errors: list[Exception] = []
        self.initial_errors: list[Exception] = []
        self.evaluation_errors: list[Exception] = []
        self.run_changes: list[tuple[int, LiveSplitRunInfo | None]] = []
        self.evaluated: list[int] = []

    def worker_started(self, connection: LiveSplitConnection) -> None:
        self.started.append(connection)

    def initial_sync_failed(
        self, connection: LiveSplitConnection, error: Exception
    ) -> None:
        self.initial_errors.append(error)

    def connection_lost(
        self, connection: LiveSplitConnection, error: Exception
    ) -> None:
        self.connection_errors.append(error)

    def worker_stopped(self, connection: LiveSplitConnection) -> None:
        self.stopped.append(connection)

    def scenario_evaluation_failed(self, scenario_index: int, error: Exception) -> None:
        self.evaluation_errors.append(error)

    def instance_run_changed(
        self, scenario_index: int, run_info: LiveSplitRunInfo | None
    ) -> None:
        self.run_changes.append((scenario_index, run_info))

    def instance_evaluated(self, scenario_index: int, context: FrameContext) -> None:
        self.evaluated.append(scenario_index)

    def snapshot_failed(
        self, connection: LiveSplitConnection, action: Action, error: Exception
    ) -> None: ...

    def snapshot_mismatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None: ...

    def action_precondition_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_succeeded(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_rejected(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None: ...

    def action_result_unknown(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None: ...

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None: ...

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None: ...

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None: ...

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None: ...


def snapshot(
    *,
    session_id: int = 1,
    event_sequence: int = 0,
    run_revision: int = 1,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 1,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=session_id,
        state_revision=event_sequence,
        event_sequence=event_sequence,
        run_revision=run_revision,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


def run_info(revision: int = 1) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=1,
        run_revision=revision,
        segments=(LiveSplitSegmentInfo(0, "A"),),
    )


def initial_update(
    *, split_count: int = 1, run: LiveSplitRunInfo | None = None
) -> LiveSplitUpdate:
    return LiveSplitUpdate(
        LiveSplitUpdateKind.INITIAL,
        snapshot(split_count=split_count),
        run,
    )


def shared_frame(captured_at: int) -> SharedFrameEvaluation:
    return SharedFrameEvaluation(
        frame=Frame(
            image=np.zeros((1, 1), dtype=np.uint8),
            captured_at=MonotonicTime(captured_at),
        ),
        now=MonotonicTime(captured_at),
    )


def wait_for(predicate: Callable[[], bool], timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition was not reached"
        time.sleep(0.001)


class Harness:
    def __init__(
        self,
        scenario: Scenario,
        *,
        initial: LiveSplitUpdate | None = None,
        execute_result: ActionExecution = ActionExecution.DISPATCHED,
        adapter: ScriptedAdapter | None = None,
        diagnostics: RecordingDiagnostics | None = None,
        log: list[str] | None = None,
    ) -> None:
        self.initial = initial if initial is not None else initial_update()
        self.execute_result = execute_result
        self.diagnostics = diagnostics or RecordingDiagnostics()
        self.subscribers: list[ScriptedSubscriber] = []
        self.adapters: list[ScriptedAdapter] = []
        self._fixed_adapter = adapter
        self._log = log
        self.instance = InstanceRuntime(
            0,
            LiveSplitConnection("rpc", "event"),
            scenario,
            diagnostics=self.diagnostics,
            reconnect_delay_seconds=0.001,
            receive_timeout_ms=1,
            subscriber_factory=self._new_subscriber,
            adapter_factory=self._new_adapter,
        )
        self._thread: threading.Thread | None = None

    def _new_subscriber(self) -> ScriptedSubscriber:
        subscriber = ScriptedSubscriber()
        self.subscribers.append(subscriber)
        return subscriber

    def _new_adapter(self) -> LiveSplitBridgeAdapter:
        adapter = self._fixed_adapter or ScriptedAdapter(
            self.initial,
            execute_result=self.execute_result,
            log=self._log,
        )
        self.adapters.append(adapter)
        return cast(LiveSplitBridgeAdapter, adapter)

    @property
    def subscriber(self) -> ScriptedSubscriber:
        return self.subscribers[-1]

    @property
    def adapter(self) -> ScriptedAdapter:
        return self.adapters[-1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self.instance.run)
        self._thread.start()

    def wait_ready(self) -> None:
        wait_for(lambda: self.instance.state is InstanceRuntimeState.READY)

    def thread_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self, timeout: float = 3) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def stop(self) -> None:
        self.instance.request_stop()
        self.join()
        assert not self.thread_alive()


def make_scenario(condition: RecordingCondition) -> Scenario:
    return Scenario(
        start_condition=condition,
        reset_condition=None,
        incomplete_condition=None,
        splits=((Rule(condition, Action("split")),),),
    )


# -- Lifecycle -----------------------------------------------------------------


def test_instance_owns_thread_reaches_ready_and_stops_cleanly() -> None:
    harness = Harness(make_scenario(RecordingCondition(False)))
    harness.start()
    try:
        harness.wait_ready()
        assert harness.adapter.attached == 1
        assert harness.instance.run_info == harness.initial.run_info
        assert harness.diagnostics.started
    finally:
        harness.stop()

    assert harness.instance.state is InstanceRuntimeState.STOPPED
    assert harness.adapter.closed
    assert harness.subscriber.closed
    assert harness.diagnostics.stopped


def test_validation_failure_is_terminal_and_isolated() -> None:
    scenario = Scenario(
        start_condition=RecordingCondition(False),
        reset_condition=None,
        incomplete_condition=None,
        splits=(None, None, None),
    )
    harness = Harness(scenario, initial=initial_update(split_count=1))
    harness.start()
    try:
        wait_for(lambda: harness.instance.state is InstanceRuntimeState.FAILED)
        wait_for(lambda: not harness.thread_alive())
    finally:
        harness.instance.request_stop()
        harness.join(2)

    assert harness.instance.state is InstanceRuntimeState.FAILED
    assert isinstance(harness.instance.error, ValueError)


# -- Frame latest-only ---------------------------------------------------------


def test_frame_latest_only_skips_superseded_frames() -> None:
    entered = threading.Event()
    release = threading.Event()

    def block(context: FrameContext) -> None:
        if not entered.is_set():
            entered.set()
            assert release.wait(3)

    condition = RecordingCondition(False, on_evaluate=block)
    harness = Harness(make_scenario(condition))
    harness.start()
    try:
        harness.wait_ready()
        harness.instance.publish_frame(shared_frame(1))
        assert entered.wait(3)
        harness.instance.publish_frame(shared_frame(2))
        harness.instance.publish_frame(shared_frame(3))
        harness.instance.publish_frame(shared_frame(4))
        release.set()

        wait_for(lambda: len(condition.captured_at) >= 2)
        wait_for(lambda: condition.captured_at[-1] == 4)
    finally:
        release.set()
        harness.stop()

    assert condition.captured_at == [1, 4]


# -- Independence and shared cache --------------------------------------------


def test_blocked_instance_does_not_block_another_instance() -> None:
    entered = threading.Event()
    release = threading.Event()

    def block(context: FrameContext) -> None:
        if not entered.is_set():
            entered.set()
            assert release.wait(3)

    slow = Harness(make_scenario(RecordingCondition(False, on_evaluate=block)))
    fast_condition = RecordingCondition(False)
    fast = Harness(make_scenario(fast_condition))
    slow.start()
    fast.start()
    try:
        slow.wait_ready()
        fast.wait_ready()
        shared = shared_frame(1)
        slow.instance.publish_frame(shared)
        fast.instance.publish_frame(shared)
        assert entered.wait(3)
        wait_for(lambda: fast_condition.calls >= 1)
        assert not release.is_set()
    finally:
        release.set()
        slow.stop()
        fast.stop()


def test_shared_cache_detects_once_across_instances() -> None:
    calls: list[int] = []

    class CountingDetector:
        @property
        def reference_images(self) -> tuple[ReferenceImage, ...]:
            return ()

        def detect(self, context: FrameContext) -> DetectionResult:
            calls.append(1)
            return DetectionResult(score=1.0)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, CountingDetector)

        def __hash__(self) -> int:
            return hash("CountingDetector")

    def scenario() -> Scenario:
        condition = Detected(CountingDetector(), 0.5)
        return Scenario(
            start_condition=condition,
            reset_condition=None,
            incomplete_condition=None,
            splits=((Rule(condition, Action("split")),),),
        )

    first = Harness(scenario())
    second = Harness(scenario())
    first.start()
    second.start()
    try:
        first.wait_ready()
        second.wait_ready()
        shared = shared_frame(1)
        first.instance.publish_frame(shared)
        second.instance.publish_frame(shared)
        wait_for(
            lambda: (
                bool(first.diagnostics.evaluated) and bool(second.diagnostics.evaluated)
            )
        )
    finally:
        first.stop()
        second.stop()

    assert calls == [1]


# -- Event ordering and Action semantics --------------------------------------


def test_bridge_event_is_applied_before_frame_evaluation() -> None:
    log: list[str] = []
    condition = RecordingCondition(
        False, on_evaluate=lambda context: log.append("eval")
    )
    harness = Harness(make_scenario(condition), log=log)
    harness.start()
    try:
        harness.wait_ready()
        harness.subscriber.push(
            LiveSplitUpdate(LiveSplitUpdateKind.TRANSITION, snapshot(event_sequence=1))
        )
        harness.instance.publish_frame(shared_frame(1))
        wait_for(lambda: "eval" in log)
    finally:
        harness.stop()

    assert log.index("event") < log.index("eval")


def test_bridge_events_are_applied_in_receive_order() -> None:
    handled: list[int] = []

    class OrderAdapter(ScriptedAdapter):
        def handle_event(self, event: object) -> object:
            result = super().handle_event(event)
            if isinstance(event, LiveSplitUpdate):
                handled.append(event.snapshot.event_sequence)
            return result

    harness = Harness(
        make_scenario(RecordingCondition(False)),
        adapter=OrderAdapter(initial_update()),
    )
    harness.start()
    try:
        harness.wait_ready()
        for sequence in (1, 2, 3):
            harness.subscriber.push(
                LiveSplitUpdate(
                    LiveSplitUpdateKind.TRANSITION, snapshot(event_sequence=sequence)
                )
            )
        wait_for(lambda: len(handled) == 3)
    finally:
        harness.stop()

    assert handled == [1, 2, 3]


def test_late_event_rejects_stale_action_without_rpc() -> None:
    entered = threading.Event()
    release = threading.Event()

    def on_evaluate(context: FrameContext) -> None:
        if not entered.is_set():
            entered.set()
            assert release.wait(3)

    condition = RecordingCondition(True, on_evaluate=on_evaluate)
    harness = Harness(make_scenario(condition))
    harness.start()
    try:
        harness.wait_ready()
        harness.instance.publish_frame(shared_frame(1))
        assert entered.wait(3)
        harness.subscriber.push(
            LiveSplitUpdate(LiveSplitUpdateKind.TRANSITION, snapshot(event_sequence=1))
        )
        release.set()
        wait_for(lambda: bool(harness.adapter.attempts))
    finally:
        release.set()
        harness.stop()

    action, expected = harness.adapter.attempts[0]
    assert action == Action("split")
    assert expected != harness.adapter.baseline


def test_action_is_dispatched_in_the_same_cycle() -> None:
    dispatched = threading.Event()

    class SignalingAdapter(ScriptedAdapter):
        def execute_action(
            self, action: Action, expected_snapshot: LiveSplitSnapshot
        ) -> ActionExecution:
            result = super().execute_action(action, expected_snapshot)
            dispatched.set()
            return result

    harness = Harness(
        make_scenario(RecordingCondition(True)),
        adapter=SignalingAdapter(initial_update()),
    )
    harness.start()
    try:
        harness.wait_ready()
        harness.instance.publish_frame(shared_frame(1))
        assert dispatched.wait(3)
    finally:
        harness.stop()

    assert [action for action, _ in harness.adapter.attempts] == [Action("split")]


def test_unknown_rpc_result_recovers_without_resend() -> None:
    harness = Harness(
        make_scenario(RecordingCondition(True)),
        execute_result=ActionExecution.UNKNOWN,
    )
    harness.start()
    try:
        harness.wait_ready()
        harness.instance.publish_frame(shared_frame(1))
        wait_for(lambda: len(harness.adapters) >= 2)
        harness.wait_ready()
    finally:
        harness.stop()

    assert harness.adapters[0].attempts
    assert harness.adapters[1].attempts == []
    assert harness.instance.generation == 1


# -- Reconnect -----------------------------------------------------------------


def test_connection_loss_rebuilds_transport_and_scenario() -> None:
    harness = Harness(make_scenario(RecordingCondition(False)))
    harness.start()
    try:
        harness.wait_ready()
        generation = harness.instance.generation
        harness.subscriber.push(BridgeConnectionLostError("lost"))
        wait_for(lambda: harness.instance.generation == generation + 1)
        wait_for(lambda: len(harness.adapters) >= 2)
        harness.wait_ready()
        assert harness.diagnostics.connection_errors
    finally:
        harness.stop()
    assert harness.adapters[0].closed
