import logging
from unittest.mock import patch

import numpy as np
import pytest
from divergencesplitter import (
    Action,
    Detected,
    Frame,
    FrameContext,
    FrameNormalizer,
    Hold,
    LiveSplitConnection,
    MeanBrightnessDetector,
    MonotonicTime,
    RisingEdge,
    Rule,
    RuleSequence,
    Scenario,
)
from divergencesplitter_runtime import (
    ActionSubmission,
    BridgeWorker,
    BridgeWorkerState,
    InstanceRuntime,
    InstanceRuntimeState,
    LatestFrameBuffer,
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    ProcessingRuntime,
)
from e2e.support import RecordingDiagnostics, snapshot


def run_info(
    *,
    session_id: int = 1,
    run_revision: int = 1,
    name: str = "A",
) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=session_id,
        run_revision=run_revision,
        segments=(LiveSplitSegmentInfo(0, name),),
    )


class ControlledWorker(BridgeWorker):
    """Drive the real worker queue without scheduling a transport thread."""

    def __init__(self) -> None:
        super().__init__(
            LiveSplitConnection("rpc", "event"), diagnostics=RecordingDiagnostics()
        )

    def initial(
        self,
        *,
        session_id: int = 1,
        split_count: int = 1,
        run: LiveSplitRunInfo | None = None,
    ) -> None:
        self._updates.replace(
            LiveSplitUpdate(
                LiveSplitUpdateKind.INITIAL,
                snapshot(session_id=session_id, split_count=split_count),
                run,
            )
        )

    def transition(
        self,
        *,
        session_id: int = 1,
        run: LiveSplitRunInfo | None = None,
    ) -> None:
        self._updates.replace(
            LiveSplitUpdate(
                LiveSplitUpdateKind.TRANSITION,
                snapshot(session_id=session_id),
                run,
            )
        )

    def resync(self) -> None:
        self._updates.replace(LiveSplitUpdate(LiveSplitUpdateKind.RESYNC, snapshot()))

    def disconnect(self) -> None:
        self._connection_lost(RuntimeError("disconnected"))

    def fail(self) -> None:
        self._fail(ValueError("invalid protocol"))


def detected() -> Detected:
    return Detected(MeanBrightnessDetector(), 0.5)


def scenario(*rules: Rule | RuleSequence, slots: int = 1) -> Scenario:
    return Scenario(
        start_condition=detected(),
        reset_condition=None,
        incomplete_condition=None,
        splits=(tuple(rules),) + (None,) * (slots - 1),
    )


def context(bright: bool = False, now: int = 0) -> FrameContext:
    return FrameContext(
        frame=Frame(
            np.full((2, 2, 3), 255 if bright else 0, dtype=np.uint8),
            MonotonicTime(now),
        ),
        now=MonotonicTime(now),
    )


def processing(*instances: InstanceRuntime) -> ProcessingRuntime:
    return ProcessingRuntime(
        instances,
        LatestFrameBuffer(),
        FrameNormalizer(),
        diagnostics=RecordingDiagnostics(),
    )


def test_independent_start_late_attach_disconnect_and_reconnect() -> None:
    a_worker, b_worker = ControlledWorker(), ControlledWorker()
    a = InstanceRuntime(scenario(), a_worker)
    b = InstanceRuntime(scenario(), b_worker)
    runtime = processing(a, b)
    assert a.scenario_runtime is b.scenario_runtime is None
    a_worker.initial()
    runtime._apply_bridge_updates()
    assert a.state is InstanceRuntimeState.READY
    assert b.state is InstanceRuntimeState.CONNECTING
    a_scenario = a.scenario_runtime
    assert a_scenario is not None
    with patch.object(a_scenario, "evaluate", wraps=a_scenario.evaluate) as evaluate:
        runtime._evaluate_scenarios(context().shared)
        assert evaluate.call_count == 1
        b_worker.initial(session_id=2)
        runtime._apply_bridge_updates()
        old_b = b.scenario_runtime
        assert old_b is not None
        assert old_b.current_snapshot == snapshot(session_id=2)
        assert a.scenario_runtime is a_scenario
        b_worker.disconnect()
        assert b.state is InstanceRuntimeState.CONNECTING
        runtime._apply_bridge_updates()
        assert b.scenario_runtime is None
        runtime._evaluate_scenarios(context(now=1).shared)
        assert evaluate.call_count == 2
        b_worker.initial(session_id=3)
        runtime._apply_bridge_updates()
        assert b.state is InstanceRuntimeState.READY
        assert b.scenario_runtime is not old_b
        assert a.scenario_runtime is a_scenario


@pytest.mark.parametrize("failure", ["validation", "protocol"])
def test_failure_is_isolated_and_terminal(failure: str) -> None:
    a_worker, b_worker = ControlledWorker(), ControlledWorker()
    a = InstanceRuntime(scenario(), a_worker)
    b = InstanceRuntime(scenario(slots=2), b_worker)
    runtime = processing(a, b)
    a_worker.initial()
    if failure == "validation":
        b_worker.initial()
    else:
        b_worker.fail()
    runtime._apply_bridge_updates()
    assert a.state is InstanceRuntimeState.READY
    assert b.state is InstanceRuntimeState.FAILED
    assert b.scenario_runtime is None
    if failure == "validation":
        assert isinstance(b.error, ValueError)
    a_scenario = a.scenario_runtime
    assert a_scenario is not None
    with patch.object(a_scenario, "evaluate", wraps=a_scenario.evaluate) as evaluate:
        runtime._evaluate_scenarios(context().shared)
        assert evaluate.call_count == 1
    b_worker.initial(split_count=3)
    runtime._apply_bridge_updates()
    assert b.state is InstanceRuntimeState.FAILED


def test_reconnect_clears_pending_action_sequence_progress_and_old_snapshot() -> None:
    sequence = RuleSequence(
        Rule(detected(), Action("pause")),
        Rule(detected(), Action("split")),
    )
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(sequence), worker)
    worker.initial()
    instance.process_updates()
    old = instance.scenario_runtime
    assert old is not None
    assert old.evaluate(context(True)) == Action("pause")
    assert sequence.active_rule_index == 1
    assert old.evaluate(context(True, 1)) is None  # Waiting for the old action.
    worker.disconnect()
    instance.process_updates()
    worker.initial(session_id=2)
    instance.process_updates()
    fresh = instance.scenario_runtime
    assert fresh is not None and fresh is not old
    assert fresh.current_snapshot == snapshot(session_id=2)
    assert sequence.active_rule_index == 0
    assert fresh.evaluate(context(True, 2)) == Action("pause")


def test_reconnect_clears_condition_edge_and_hold_history() -> None:
    edge = RisingEdge(detected())
    hold = Hold(detected(), 10)
    worker = ControlledWorker()
    instance = InstanceRuntime(
        scenario(Rule(edge, Action("split")), Rule(hold, Action("pause"))), worker
    )
    worker.initial()
    instance.process_updates()
    old = instance.scenario_runtime
    assert old is not None
    assert old.evaluate(context(False)) is None  # Arms the old rising edge.
    # Exercise Hold's history independently, without firing a pending action.
    assert hold.evaluate(context(True, 1)) is False
    worker.disconnect()
    instance.process_updates()
    worker.initial()
    instance.process_updates()
    fresh = instance.scenario_runtime
    assert fresh is not None
    assert hold.elapsed_nanoseconds is None
    assert fresh.evaluate(context(True, 20)) is None  # Neither old edge nor hold fires.
    assert fresh.evaluate(context(True, 30)) == Action("pause")


def test_same_session_resync_keeps_runtime_and_generation() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial()
    instance.process_updates()
    original = instance.scenario_runtime
    worker.resync()
    instance.process_updates()
    assert instance.state is InstanceRuntimeState.READY
    assert instance.scenario_runtime is original
    assert instance.generation == 0


def test_fast_reconnect_rejects_action_from_previous_generation() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial()
    instance.process_updates()
    generation = instance.generation
    worker.disconnect()
    worker.initial()  # Same Bridge session/snapshot, but a new execution session.
    instance.process_updates()
    assert (
        worker.submit_action(Action("split"), snapshot(), generation=generation)
        is ActionSubmission.REJECTED
    )
    assert (
        worker.submit_action(
            Action("split"), snapshot(), generation=instance.generation
        )
        is ActionSubmission.ACCEPTED
    )


def test_initial_is_validated_before_ready_and_lifecycle_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = ControlledWorker()
    with caplog.at_level(logging.INFO):
        instance = InstanceRuntime(scenario(), worker)
        worker.initial()
        assert instance.state is InstanceRuntimeState.CONNECTING
        instance.process_updates()
        assert instance.state is InstanceRuntimeState.READY
        assert instance.scenario_runtime is not None
        assert instance.scenario_runtime.current_snapshot == snapshot()
        worker.disconnect()
        instance.process_updates()
        worker.initial()
        instance.process_updates()
    events = [record.message for record in caplog.records]
    for event in (
        "instance.connecting",
        "instance.ready",
        "instance.connection_lost",
        "instance.reinitialized",
    ):
        assert event in events
    instance.stop()
    assert instance.state is InstanceRuntimeState.STOPPED
    assert instance.scenario_runtime is None


def test_initial_establishes_current_run_info() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    expected = run_info(run_revision=3)

    worker.initial(run=expected)
    instance.process_updates()

    assert instance.state is InstanceRuntimeState.READY
    assert instance.run_info == expected


def test_transition_replaces_current_run_info() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial(run=run_info(run_revision=1))
    instance.process_updates()

    worker.transition(run=run_info(run_revision=2, name="B"))
    instance.process_updates()

    assert instance.run_info == run_info(run_revision=2, name="B")


def test_transition_without_run_info_keeps_current_run_info() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial(run=run_info(run_revision=1))
    instance.process_updates()

    worker.transition()
    instance.process_updates()

    assert instance.run_info == run_info(run_revision=1)


def test_generation_change_discards_run_info() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial(run=run_info(run_revision=1))
    instance.process_updates()

    worker.disconnect()
    instance.process_updates()

    assert instance.run_info is None


def test_worker_failure_discards_run_info() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial(run=run_info(run_revision=1))
    instance.process_updates()

    worker.fail()
    instance.process_updates()

    assert instance.state is InstanceRuntimeState.FAILED
    assert instance.run_info is None


def test_stop_discards_run_info() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial(run=run_info(run_revision=1))
    instance.process_updates()

    instance.stop()

    assert instance.run_info is None
    assert instance.state is InstanceRuntimeState.STOPPED


def test_run_info_change_does_not_change_lifecycle_status() -> None:
    worker = ControlledWorker()
    instance = InstanceRuntime(scenario(), worker)
    worker.initial(run=run_info(run_revision=1))
    instance.process_updates()
    before = instance.status(0)

    worker.transition(run=run_info(run_revision=2))
    instance.process_updates()

    assert instance.run_info == run_info(run_revision=2)
    assert instance.status(0) == before


def test_drain_cannot_revive_a_failed_or_disconnected_worker() -> None:
    worker = ControlledWorker()
    worker.initial()
    worker.disconnect()
    assert worker.drain_updates() == ()
    assert worker.state is BridgeWorkerState.CONNECTING
    worker.initial()
    worker.fail()
    assert worker.drain_updates() == ()
    assert worker.state is BridgeWorkerState.FAILED
