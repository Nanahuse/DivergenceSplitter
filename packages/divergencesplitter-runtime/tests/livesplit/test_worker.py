import logging
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import ClassVar, Self
from unittest.mock import patch

import pytest
from divergencesplitter import (
    Action,
    ErrorAction,
    Frame,
    FrameContext,
    FrameNormalizationError,
    FrameNormalizer,
    FrameSourceError,
    FrameSourceState,
    LiveSplitConnection,
    MonotonicTime,
    Scenario,
)
from divergencesplitter_runtime import (
    ActionSubmission,
    ApplicationRuntime,
    BridgeActionRequest,
    BridgeWorker,
    BridgeWorkerState,
    InstanceRuntimeState,
    LiveSplitResyncReason,
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    ScenarioInstance,
    TimerPhase,
)
from divergencesplitter_runtime.livesplit.worker import _ActionSlot
from livesplit_bridge import (
    BridgeConnectionLostError,
    BridgeProtocolError,
    BridgeResponseTimeoutError,
)


def snapshot(
    *,
    session_id: int = 1,
    event_sequence: int = 0,
    run_revision: int = 1,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=session_id,
        state_revision=event_sequence,
        event_sequence=event_sequence,
        run_revision=run_revision,
        phase=TimerPhase.RUNNING,
        split_index=0,
        split_count=1,
    )


def run_info(
    *,
    session_id: int = 1,
    run_revision: int = 1,
) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=session_id,
        run_revision=run_revision,
        segments=(LiveSplitSegmentInfo(0, "A"),),
    )


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.submissions: list[tuple[BridgeActionRequest, ActionSubmission]] = []
        self.connection_errors: list[Exception] = []
        self.reconnect_errors: list[Exception] = []
        self.overflow_count = 0

    def worker_started(self, connection: LiveSplitConnection) -> None:
        pass

    def initial_sync_failed(
        self, connection: LiveSplitConnection, error: Exception
    ) -> None:
        self.connection_errors.append(error)

    def connection_lost(
        self, connection: LiveSplitConnection, error: Exception
    ) -> None:
        self.connection_errors.append(error)

    def reconnect_failed(
        self, connection: LiveSplitConnection, error: Exception
    ) -> None:
        self.reconnect_errors.append(error)

    def update_queue_overflowed(self, connection: LiveSplitConnection) -> None:
        self.overflow_count += 1

    def action_submitted(
        self,
        connection: LiveSplitConnection,
        request: BridgeActionRequest,
        result: ActionSubmission,
    ) -> None:
        self.submissions.append((request, result))

    def worker_stopped(self, connection: LiveSplitConnection) -> None:
        pass

    def scenario_logger(self, scenario_index: int) -> logging.Logger:
        return logging.getLogger(f"test-worker-scenario-{scenario_index}")

    def instances_changed(self, statuses) -> None:
        pass

    def runtime_started(self) -> None:
        pass

    def preparing(self) -> None:
        pass

    def prepared(self) -> None:
        pass

    def frame_received(self, frame: Frame, publish_result: object) -> None:
        pass

    def source_error(self, error: FrameSourceError) -> None:
        pass

    def error_handled(self, action: ErrorAction, state: FrameSourceState) -> None:
        pass

    def source_state_changed(
        self,
        previous: FrameSourceState | None,
        current: FrameSourceState,
    ) -> None:
        pass

    def source_state_unavailable(self, error: Exception) -> None:
        pass

    def source_closed(self) -> None:
        pass

    def stopped(self) -> None:
        pass

    def frame_processing_started(
        self,
        frame: Frame,
        processing_started_at: MonotonicTime,
    ) -> None:
        pass

    def frame_normalization_failed(self, error: FrameNormalizationError) -> None:
        pass

    def frame_processing_completed(self, context: FrameContext) -> None:
        pass

    def scenario_evaluation_failed(
        self,
        scenario_index: int,
        error: Exception,
    ) -> None:
        pass

    def snapshot_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        error: Exception,
    ) -> None:
        pass

    def snapshot_mismatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_precondition_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_succeeded(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_rejected(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None:
        pass

    def action_result_unknown(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None:
        pass

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None:
        pass

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None:
        pass

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None:
        pass

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        pass


class FakeAdapter:
    instances: ClassVar[list[FakeAdapter]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.created_on = threading.get_ident()
        self.closed = False
        self.receives: list[
            LiveSplitUpdate | LiveSplitResyncReason | Exception | None
        ] = []
        self.executed: list[tuple[Action, LiveSplitSnapshot]] = []
        self.reconnect_results: list[LiveSplitUpdate | Exception] = []
        self.resync_result = LiveSplitUpdate(
            LiveSplitUpdateKind.RESYNC,
            snapshot(event_sequence=99),
        )
        self.resynced = threading.Event()
        FakeAdapter.instances.append(self)

    def attach(self) -> LiveSplitUpdate:
        return LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, snapshot())

    def receive(
        self,
        *,
        timeout_ms: int | None = None,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        if self.receives:
            result = self.receives.pop(0)
            if isinstance(result, Exception):
                self.is_synchronized = False
                raise result
            return result
        time.sleep((timeout_ms or 0) / 1000)
        return None

    def reconnect(self) -> LiveSplitUpdate:
        result = self.reconnect_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
        self.resynced.set()
        return self.resync_result

    def execute_action(
        self, action: Action, expected_snapshot: LiveSplitSnapshot
    ) -> None:
        self.executed.append((action, expected_snapshot))

    def close(self) -> None:
        self.closed = True


class FailingAttachAdapter(FakeAdapter):
    def attach(self) -> LiveSplitUpdate:
        raise RuntimeError("attach failed")


def start_worker(worker: BridgeWorker) -> threading.Thread:
    thread = threading.Thread(target=worker.run)
    thread.start()
    worker.wait_until_initialized(1)
    return thread


def stop_worker(worker: BridgeWorker, thread: threading.Thread) -> None:
    worker.request_stop()
    thread.join(1)
    assert not thread.is_alive()


def test_worker_constructs_and_closes_adapter_on_worker_thread() -> None:
    FakeAdapter.instances.clear()
    diagnostics = RecordingDiagnostics()
    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"),
        diagnostics=diagnostics,
        receive_timeout_ms=1,
    )
    caller_thread = threading.get_ident()

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        FakeAdapter,
    ):
        thread = start_worker(worker)
        adapter = FakeAdapter.instances[-1]
        stop_worker(worker, thread)

    assert adapter.created_on != caller_thread
    assert adapter.closed


def test_action_slot_is_bounded_and_reset_replaces_pending_normal_action() -> None:
    slot = _ActionSlot()
    split = BridgeActionRequest(Action("split"), snapshot())
    reset = BridgeActionRequest(Action("reset"), snapshot())
    assert slot.submit(split) is ActionSubmission.ACCEPTED
    assert slot.submit(split) is ActionSubmission.REJECTED
    assert slot.submit(reset) is ActionSubmission.RESET_REPLACED
    assert slot.submit(split) is ActionSubmission.REJECTED
    assert slot.take() == reset


def test_stopped_worker_rejects_new_action() -> None:
    diagnostics = RecordingDiagnostics()
    worker = BridgeWorker(LiveSplitConnection("rpc", "event"), diagnostics=diagnostics)
    worker.request_stop()

    result = worker.submit_action(Action("reset"), snapshot())

    assert result is ActionSubmission.STOPPED


def test_worker_reports_initial_attach_failure_and_closes_adapter() -> None:
    FakeAdapter.instances.clear()
    diagnostics = RecordingDiagnostics()
    worker = BridgeWorker(LiveSplitConnection("rpc", "event"), diagnostics=diagnostics)

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        FailingAttachAdapter,
    ):
        thread = threading.Thread(target=worker.run)
        thread.start()
        with pytest.raises(RuntimeError, match="attach failed"):
            worker.wait_until_initialized(1)
        thread.join(1)

    assert not thread.is_alive()
    assert isinstance(diagnostics.connection_errors[0], RuntimeError)
    assert FakeAdapter.instances[-1].closed


def test_worker_validates_update_capacity_and_initialization_wait_timeout() -> None:
    diagnostics = RecordingDiagnostics()
    with pytest.raises(ValueError, match="capacity"):
        BridgeWorker(
            LiveSplitConnection("rpc", "event"),
            diagnostics=diagnostics,
            update_capacity=0,
        )

    worker = BridgeWorker(LiveSplitConnection("rpc", "event"), diagnostics=diagnostics)
    with pytest.raises(TimeoutError, match="initial synchronization"):
        worker.wait_until_initialized(0)


def test_update_overflow_replaces_pending_updates_with_resync() -> None:
    FakeAdapter.instances.clear()
    diagnostics = RecordingDiagnostics()
    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"),
        diagnostics=diagnostics,
        receive_timeout_ms=1,
        update_capacity=1,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        FakeAdapter,
    ):
        thread = start_worker(worker)
        adapter = FakeAdapter.instances[-1]
        adapter.resync_result = LiveSplitUpdate(
            LiveSplitUpdateKind.RESYNC,
            snapshot(event_sequence=99),
            run_info(run_revision=4),
        )
        adapter.receives.append(
            LiveSplitUpdate(
                LiveSplitUpdateKind.TRANSITION,
                snapshot(event_sequence=1),
            )
        )
        assert adapter.resynced.wait(1)
        updates = worker.drain_updates()
        stop_worker(worker, thread)

    assert diagnostics.overflow_count == 1
    assert updates == (
        LiveSplitUpdate(
            LiveSplitUpdateKind.INITIAL,
            adapter.resync_result.snapshot,
            run_info(run_revision=4),
        ),
    )


def test_connection_loss_uses_fresh_adapter_and_publishes_initial() -> None:
    FakeAdapter.instances.clear()
    diagnostics = RecordingDiagnostics()
    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"),
        diagnostics=diagnostics,
        receive_timeout_ms=1,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        FakeAdapter,
    ):
        thread = start_worker(worker)
        adapter = FakeAdapter.instances[-1]
        worker.drain_updates()
        expected = LiveSplitUpdate(
            LiveSplitUpdateKind.INITIAL,
            snapshot(),
        )
        adapter.receives.append(BridgeConnectionLostError("heartbeat missing"))
        deadline = time.monotonic() + 1
        updates: tuple[LiveSplitUpdate, ...] = ()
        while not updates and time.monotonic() < deadline:
            updates = worker.drain_updates()
            time.sleep(0.001)
        stop_worker(worker, thread)

    assert adapter.closed
    assert len(FakeAdapter.instances) == 2
    assert updates == (expected,)
    assert len(diagnostics.connection_errors) == 1


class PassiveCondition:
    @property
    def children(self) -> tuple:
        return ()

    def evaluate(self, context: object, *, is_short_circuited: bool = False) -> bool:
        return False

    def reset(self) -> None:
        pass


class StoppingSource:
    def __init__(self) -> None:
        self.state = FrameSourceState.NOT_READY
        self.normalizer = FrameNormalizer()
        self.prepare_calls = 0
        self.close_calls = 0

    def prepare(self) -> None:
        self.prepare_calls += 1
        self.state = FrameSourceState.READY

    def read(self) -> FrameSourceError:
        return FrameSourceError()

    def handle_error(self, error: FrameSourceError) -> ErrorAction:
        return ErrorAction.STOP

    def close(self) -> None:
        self.close_calls += 1
        self.state = FrameSourceState.NOT_READY

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def scenario(*, split_slots: int = 1) -> ScenarioInstance:
    return ScenarioInstance(
        connection=LiveSplitConnection("rpc", "event"),
        scenario=Scenario(
            start_condition=PassiveCondition(),
            reset_condition=PassiveCondition(),
            incomplete_condition=None,
            splits=(None,) * split_slots,
        ),
    )


def test_application_starts_shared_capture() -> None:
    FakeAdapter.instances.clear()
    source = StoppingSource()
    runtime = ApplicationRuntime(
        (scenario(),),
        source,
        diagnostics=RecordingDiagnostics(),
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        FakeAdapter,
    ):
        runtime.run()

    assert source.prepare_calls == 1
    assert source.close_calls == 1
    assert FakeAdapter.instances[-1].closed


def test_application_starts_capture_even_when_split_count_is_invalid() -> None:
    FakeAdapter.instances.clear()
    source = StoppingSource()
    runtime = ApplicationRuntime(
        (scenario(split_slots=3),),
        source,
        diagnostics=RecordingDiagnostics(),
    )

    with (
        patch(
            "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
            FakeAdapter,
        ),
    ):
        runtime.run()

    assert source.prepare_calls == 1
    assert source.close_calls == 1


def wait_for(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


@pytest.mark.parametrize(
    "loss", [BridgeConnectionLostError("lost"), LiveSplitResyncReason.SESSION_CHANGED]
)
def test_reconnection_drops_queued_actions_and_replaces_adapter(
    loss: Exception | LiveSplitResyncReason,
) -> None:
    FakeAdapter.instances.clear()
    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"),
        diagnostics=RecordingDiagnostics(),
        receive_timeout_ms=1,
        reconnect_delay_seconds=0,
    )
    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        FakeAdapter,
    ):
        thread = start_worker(worker)
        try:
            old_adapter = FakeAdapter.instances[-1]
            worker.drain_updates()
            generation = worker.connection_state[1]
            old_adapter.receives.append(loss)
            wait_for(lambda: len(FakeAdapter.instances) == 2)
            updates: list[LiveSplitUpdate] = []

            def received_initial() -> bool:
                updates.extend(worker.drain_updates())
                return bool(updates)

            wait_for(received_initial)
            assert updates[0].kind is LiveSplitUpdateKind.INITIAL
            assert old_adapter.closed
            assert (
                worker.submit_action(Action("split"), snapshot(), generation=generation)
                is ActionSubmission.REJECTED
            )
            assert FakeAdapter.instances[-1].executed == []
        finally:
            stop_worker(worker, thread)


def test_initial_attach_retries_fresh_adapters_until_available() -> None:
    FakeAdapter.instances.clear()
    available = threading.Event()

    class RetryAdapter(FakeAdapter):
        def attach(self) -> LiveSplitUpdate:
            if not available.is_set():
                raise BridgeResponseTimeoutError("Bridge not running")
            return super().attach()

    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"),
        diagnostics=RecordingDiagnostics(),
        reconnect_delay_seconds=0.001,
    )
    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        RetryAdapter,
    ):
        thread = threading.Thread(target=worker.run)
        thread.start()
        try:
            wait_for(lambda: len(FakeAdapter.instances) >= 2)
            assert worker.state is BridgeWorkerState.CONNECTING
            assert thread.is_alive()
            assert FakeAdapter.instances[0].closed
            available.set()
            worker.wait_until_initialized(2)
            assert worker.drain_updates()[0].kind is LiveSplitUpdateKind.INITIAL
            assert worker.state is BridgeWorkerState.READY
        finally:
            stop_worker(worker, thread)
    assert all(adapter.closed for adapter in FakeAdapter.instances)


def test_application_starts_and_stops_while_bridge_keeps_retrying() -> None:
    class OfflineAdapter(FakeAdapter):
        def attach(self) -> LiveSplitUpdate:
            raise BridgeResponseTimeoutError("Bridge offline")

    source = StoppingSource()
    runtime = ApplicationRuntime(
        (scenario(),), source, diagnostics=RecordingDiagnostics()
    )
    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        OfflineAdapter,
    ):
        thread = threading.Thread(target=runtime.run)
        thread.start()
        thread.join(2)
        try:
            assert not thread.is_alive()
        finally:
            runtime.request_stop()
            thread.join(2)
    assert source.prepare_calls == source.close_calls == 1
    assert runtime.instances[0].state is InstanceRuntimeState.STOPPED


@pytest.mark.parametrize(
    "error", [BridgeProtocolError("invalid protocol"), ValueError("bad snapshot")]
)
def test_protocol_failure_does_not_retry(error: Exception) -> None:
    FakeAdapter.instances.clear()

    class InvalidAdapter(FakeAdapter):
        def attach(self) -> LiveSplitUpdate:
            raise error

    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"), diagnostics=RecordingDiagnostics()
    )
    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        InvalidAdapter,
    ):
        thread = threading.Thread(target=worker.run)
        thread.start()
        thread.join(2)
    assert not thread.is_alive()
    assert worker.state is BridgeWorkerState.FAILED
    assert len(FakeAdapter.instances) == 1
    assert FakeAdapter.instances[0].closed


def test_draining_initial_during_resync_does_not_enable_actions() -> None:
    FakeAdapter.instances.clear()
    entered, release = threading.Event(), threading.Event()

    class BlockingResyncAdapter(FakeAdapter):
        def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
            entered.set()
            assert release.wait(2)
            return super().resync(reason)

    worker = BridgeWorker(
        LiveSplitConnection("rpc", "event"),
        diagnostics=RecordingDiagnostics(),
        receive_timeout_ms=1,
    )
    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        BlockingResyncAdapter,
    ):
        thread = start_worker(worker)
        try:
            adapter = FakeAdapter.instances[-1]
            adapter.receives.append(LiveSplitResyncReason.GAP)
            assert entered.wait(2)
            assert worker.drain_updates()[0].kind is LiveSplitUpdateKind.INITIAL
            assert not worker.is_available
            assert (
                worker.submit_action(Action("split"), snapshot())
                is ActionSubmission.REJECTED
            )
            release.set()
            updates: list[LiveSplitUpdate] = []

            def completed() -> bool:
                updates.extend(worker.drain_updates())
                return bool(updates)

            wait_for(completed)
            assert updates[0].kind is LiveSplitUpdateKind.RESYNC
            assert worker.is_available
            assert len(FakeAdapter.instances) == 1
        finally:
            release.set()
            stop_worker(worker, thread)
