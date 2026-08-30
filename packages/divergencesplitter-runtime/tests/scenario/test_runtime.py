import logging
import unittest
from typing import Literal, overload

import numpy as np
from divergencesplitter import (
    Action,
    Frame,
    FrameContext,
    LiveSplitConnection,
    MonotonicTime,
    Rule,
    Scenario,
)
from divergencesplitter_runtime import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    ScenarioRuntime,
    TimerPhase,
)


class RecordingCondition:
    def __init__(self, result: bool, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0
        self.resets = 0

    @overload
    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: Literal[False] = False,
    ) -> bool: ...

    @overload
    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: Literal[True],
    ) -> bool | None: ...

    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: bool = False,
    ) -> bool | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result

    def reset(self) -> None:
        self.resets += 1


class RaisingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        raise RuntimeError("logging failed")


def make_action(operation: str = "split") -> Action:
    return Action(operation=operation)


def make_rule(
    condition: RecordingCondition,
    operation: str = "split",
) -> Rule:
    return Rule(condition=condition, action=make_action(operation))


def make_scenario(
    splits: tuple[tuple[Rule, ...] | None, ...],
    *,
    reset_conditions: tuple[RecordingCondition, ...] | None = None,
) -> Scenario:
    return Scenario(
        connection=LiveSplitConnection("rpc", "event"),
        reset_conditions=reset_conditions or (RecordingCondition(False),),
        splits=splits,
    )


def make_snapshot(
    *,
    session_id: int = 1,
    state_revision: int = 0,
    event_sequence: int = 0,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 2,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=session_id,
        state_revision=state_revision,
        event_sequence=event_sequence,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


def update(
    snapshot: LiveSplitSnapshot,
    kind: LiveSplitUpdateKind = LiveSplitUpdateKind.INITIAL,
) -> LiveSplitUpdate:
    return LiveSplitUpdate(kind=kind, snapshot=snapshot)


def context(nanoseconds: int = 0) -> FrameContext:
    return FrameContext(
        frame=Frame(
            image=np.zeros((1, 1), dtype=np.uint8),
            captured_at=MonotonicTime(nanoseconds),
        ),
        now=MonotonicTime(nanoseconds),
    )


class ModelValidationTest(unittest.TestCase):
    def test_action_rejects_unsupported_operation(self) -> None:
        with self.assertRaises(ValueError):
            make_action("start")

    def test_snapshot_phase_invariants_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            make_snapshot(phase=TimerPhase.NOT_RUNNING, split_index=0)
        with self.assertRaises(ValueError):
            make_snapshot(phase=TimerPhase.ENDED, split_index=0, split_count=0)


class ScenarioRuntimeEvaluationTest(unittest.TestCase):
    def test_current_snapshot_is_none_before_sync_and_tracks_baseline(self) -> None:
        runtime = ScenarioRuntime(make_scenario((None,)))
        self.assertIsNone(runtime.current_snapshot)
        snapshot = make_snapshot(split_count=1)

        runtime.apply_livesplit_update(update(snapshot))

        self.assertIs(runtime.current_snapshot, snapshot)

    def test_initial_baseline_resets_every_rule_without_evaluating(self) -> None:
        reset = RecordingCondition(False)
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(first),), None, (make_rule(second),)),
                reset_conditions=(reset,),
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        self.assertEqual((reset.resets, first.resets, second.resets), (0, 0, 0))
        runtime.apply_livesplit_update(update(make_snapshot()))
        self.assertEqual((reset.resets, first.resets, second.resets), (1, 1, 1))
        self.assertEqual((reset.calls, first.calls, second.calls), (0, 0, 0))

    def test_reset_is_evaluated_first_and_blocks_main_until_result(self) -> None:
        reset = RecordingCondition(True)
        main = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(main),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        action = runtime.evaluate(context())
        self.assertEqual(action, Action(operation="reset"))
        self.assertEqual((reset.calls, main.calls), (1, 0))
        self.assertIsNone(runtime.evaluate(context(1)))
        self.assertEqual(reset.calls, 1)

    def test_reset_exception_does_not_block_remaining_or_main_rules(self) -> None:
        failing = RecordingCondition(False, error=RuntimeError("failed"))
        succeeding_reset = RecordingCondition(False)
        main = RecordingCondition(True)
        logger = logging.getLogger(f"raising.{self.id()}")
        logger.handlers.clear()
        logger.propagate = False
        logger.addHandler(RaisingHandler())
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(main),),),
                reset_conditions=(failing, succeeding_reset),
            ),
            logger=logger,
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        self.assertEqual(runtime.evaluate(context()), Action(operation="split"))
        self.assertEqual((failing.calls, succeeding_reset.calls, main.calls), (1, 1, 1))

    def test_reset_supersedes_normal_action_wait(self) -> None:
        reset = RecordingCondition(False)
        main = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(main),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        self.assertEqual(runtime.evaluate(context()), Action(operation="split"))
        reset.result = True
        self.assertEqual(runtime.evaluate(context(1)), Action(operation="reset"))

    def test_main_rules_are_ordered_and_exceptions_skip_only_one_rule(self) -> None:
        failing = RecordingCondition(False, error=RuntimeError("failed"))
        first_match = RecordingCondition(True)
        later_match = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(
                (
                    (
                        make_rule(failing),
                        make_rule(first_match, "skip"),
                        make_rule(later_match, "undo"),
                    ),
                )
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        self.assertEqual(runtime.evaluate(context()), Action(operation="skip"))
        self.assertEqual(
            (failing.calls, first_match.calls, later_match.calls), (1, 1, 0)
        )

    def test_ended_evaluates_completion_slot(self) -> None:
        completion = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario((None, None, (make_rule(completion, "undo"),)))
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.ENDED,
                    split_index=2,
                    split_count=2,
                )
            )
        )
        self.assertEqual(runtime.evaluate(context()), Action(operation="undo"))
        self.assertEqual(completion.calls, 1)

    def test_none_missing_and_not_running_slots_do_not_evaluate_main(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_scenario((None, (make_rule(condition),))))
        runtime.apply_livesplit_update(update(make_snapshot(split_index=0)))
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=1,
                    state_revision=1,
                    split_index=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertIsNotNone(runtime.evaluate(context()))

        unloaded = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        unloaded.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.NOT_RUNNING,
                    split_index=-1,
                    split_count=0,
                )
            )
        )
        calls = condition.calls
        self.assertIsNone(unloaded.evaluate(context()))
        self.assertEqual(condition.calls, calls)


class ScenarioRuntimeUpdateTest(unittest.TestCase):
    def test_transition_resets_only_destination_including_completion(self) -> None:
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        completion = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(
                (
                    (make_rule(first),),
                    (make_rule(second),),
                    (make_rule(completion),),
                )
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot()))
        baseline = (first.resets, second.resets, completion.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=1, state_revision=1, split_index=1),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(
            (first.resets, second.resets, completion.resets),
            (baseline[0], baseline[1] + 1, baseline[2]),
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=2,
                    state_revision=2,
                    phase=TimerPhase.ENDED,
                    split_index=2,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(completion.resets, baseline[2] + 1)

    def test_pause_and_resume_do_not_reset_current_group(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=1,
                    state_revision=1,
                    phase=TimerPhase.PAUSED,
                    split_count=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=2,
                    state_revision=2,
                    split_count=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(condition.resets, baseline)

    def test_same_position_transition_resets_destination_group(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=1,
                    state_revision=1,
                    split_count=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(condition.resets, baseline + 1)

    def test_confirmed_reset_and_state_changing_resync_reset_all_rules(self) -> None:
        reset = RecordingCondition(False)
        main = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(main),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = (reset.resets, main.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=1,
                    state_revision=1,
                    phase=TimerPhase.NOT_RUNNING,
                    split_index=-1,
                    split_count=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(
            (reset.resets, main.resets), (baseline[0] + 1, baseline[1] + 1)
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    event_sequence=2,
                    state_revision=2,
                    split_count=1,
                ),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(
            (reset.resets, main.resets), (baseline[0] + 2, baseline[1] + 2)
        )

    def test_unchanged_resync_retains_rule_state(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=1, split_count=1),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(condition.resets, baseline)

    def test_gap_stops_evaluation_until_resync(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=2, split_count=1),
                LiveSplitUpdateKind.PERIODIC,
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=2, split_count=1),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(runtime.evaluate(context()), Action(operation="split"))

    def test_session_change_requires_resync_and_resets_all(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        runtime.apply_livesplit_update(
            update(
                make_snapshot(session_id=2, split_count=1),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(session_id=2, split_count=1),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(condition.resets, baseline + 1)

    def test_periodic_duplicate_and_out_of_order_updates_do_not_reset(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(
            update(make_snapshot(event_sequence=2, split_count=1))
        )
        baseline = condition.resets
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=3, split_count=1),
                LiveSplitUpdateKind.PERIODIC,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=3, split_count=1),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=1, split_count=1),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(condition.resets, baseline)

    def test_too_many_slots_stop_evaluation_until_valid_resync(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(condition),), None, None, None))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=1, split_count=3),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(runtime.evaluate(context()), Action(operation="split"))

    def test_run_change_resets_all_rules(self) -> None:
        reset = RecordingCondition(False)
        main = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(main),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = (reset.resets, main.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=1, split_count=2),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(
            (reset.resets, main.resets), (baseline[0] + 1, baseline[1] + 1)
        )


class ScenarioRuntimeTimeoutTest(unittest.TestCase):
    def test_normal_timeout_resets_current_group_and_restarts(self) -> None:
        reset = RecordingCondition(False)
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(condition),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        self.assertEqual(runtime.evaluate(context(10)), Action(operation="split"))
        self.assertIsNone(runtime.evaluate(context(1_000_000_009)))
        self.assertIsNone(runtime.evaluate(context(1_000_000_010)))
        self.assertEqual(condition.resets, baseline + 1)
        self.assertEqual(reset.calls, 3)
        self.assertEqual(
            runtime.evaluate(context(1_000_000_011)), Action(operation="split")
        )


if __name__ == "__main__":
    unittest.main()
