import logging
import unittest
from typing import Literal, overload

import numpy as np
from divergencesplitter import (
    Action,
    Frame,
    FrameContext,
    MonotonicTime,
    Rule,
    Scenario,
)
from divergencesplitter_runtime import (
    LiveSplitSnapshot,
    LiveSplitTransitionReason,
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

    @property
    def children(self) -> tuple:
        return ()

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
    start_condition: RecordingCondition | None = None,
    incomplete_condition: RecordingCondition | None = None,
) -> Scenario:
    reset = (reset_conditions or (RecordingCondition(False),))[0]
    return Scenario(
        start_condition=start_condition or RecordingCondition(False),
        reset_condition=reset,
        incomplete_condition=incomplete_condition,
        splits=splits,
    )


def make_snapshot(
    *,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 2,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


def update(
    snapshot: LiveSplitSnapshot,
    kind: LiveSplitUpdateKind = LiveSplitUpdateKind.INITIAL,
    *,
    session_id: int = 1,
    event_sequence: int | None = None,
    state_epoch: int = 0,
    run_structure_changed: bool = False,
    transition: LiveSplitTransitionReason | None = None,
) -> LiveSplitUpdate:
    return LiveSplitUpdate(
        kind=kind,
        snapshot=snapshot,
        session_id=session_id,
        event_sequence=event_sequence,
        state_epoch=state_epoch,
        run_structure_changed=run_structure_changed,
        transition=transition,
    )


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
            make_action("unsupported")

    def test_snapshot_phase_invariants_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            make_snapshot(phase=TimerPhase.NOT_RUNNING, split_index=0)
        with self.assertRaises(ValueError):
            make_snapshot(phase=TimerPhase.ENDED, split_index=0, split_count=0)


class ScenarioRuntimeEvaluationTest(unittest.TestCase):
    def test_action_not_dispatched_clears_pending_and_allows_refire(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))

        self.assertEqual(runtime.evaluate(context(10)), Action("split"))
        self.assertIsNone(runtime.evaluate(context(20)))  # Waiting for dispatch.
        runtime.action_not_dispatched(Action("split"))
        self.assertEqual(runtime.evaluate(context(30)), Action("split"))

    def test_action_not_dispatched_is_noop_without_pending_action(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))

        runtime.action_not_dispatched(Action("split"))

        self.assertIsNone(runtime.evaluate(context(10)))

    def test_not_running_evaluates_start_only(self) -> None:
        start = RecordingCondition(True)
        reset = RecordingCondition(True)
        split = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(split),),),
                reset_conditions=(reset,),
                start_condition=start,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.NOT_RUNNING, split_index=-1, split_count=1
                )
            )
        )

        assert runtime.evaluate(context()) == Action("start")
        assert (start.calls, reset.calls, split.calls) == (1, 0, 0)

    def test_running_does_not_evaluate_start(self) -> None:
        start = RecordingCondition(True)
        runtime = ScenarioRuntime(make_scenario((), start_condition=start))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(phase=TimerPhase.RUNNING, split_index=0, split_count=1)
            )
        )

        assert runtime.evaluate(context()) is None
        assert start.calls == 0

    def test_ended_without_incomplete_condition_keeps_runtime_idle(self) -> None:
        runtime = ScenarioRuntime(make_scenario((None,)))
        runtime.apply_livesplit_update(
            update(make_snapshot(phase=TimerPhase.ENDED, split_index=1, split_count=1))
        )

        assert runtime.evaluate(context()) is None

    def test_incomplete_undo_is_pending_and_retried_after_timeout(self) -> None:
        incomplete = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario((None,), incomplete_condition=incomplete)
        )
        runtime.apply_livesplit_update(
            update(make_snapshot(phase=TimerPhase.ENDED, split_index=1, split_count=1))
        )

        assert runtime.evaluate(context(10)) == Action("undo")
        assert runtime.evaluate(context(20)) is None
        assert incomplete.calls == 1
        runtime.action_accepted(Action("undo"), 10)
        runtime.state_wait_timed_out(1_000_000_010)
        assert runtime.evaluate(context(1_000_000_011)) == Action("undo")

    def test_manual_undo_resets_ended_conditions_before_running(self) -> None:
        incomplete = RecordingCondition(False)
        reset = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(
                (None,),
                reset_conditions=(reset,),
                incomplete_condition=incomplete,
            )
        )
        runtime.apply_livesplit_update(
            update(make_snapshot(phase=TimerPhase.ENDED, split_index=1, split_count=1))
        )
        ended_resets = (reset.resets, incomplete.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.RUNNING,
                    split_index=0,
                    split_count=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )

        assert reset.resets == ended_resets[0] + 1
        assert incomplete.resets == ended_resets[1] + 1

    def test_current_snapshot_is_none_before_sync_and_tracks_baseline(self) -> None:
        runtime = ScenarioRuntime(make_scenario((None,)))
        self.assertIsNone(runtime.current_snapshot)
        snapshot = make_snapshot(split_count=1)

        runtime.apply_livesplit_update(update(snapshot))

        self.assertEqual(runtime.current_snapshot, snapshot)

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
        self.assertEqual((failing.calls, succeeding_reset.calls, main.calls), (1, 0, 1))

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

    def test_ended_evaluates_incomplete_condition(self) -> None:
        completion = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario((None, None), incomplete_condition=completion)
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
    def test_transition_resets_only_destination(self) -> None:
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(first),), (make_rule(second),)))
        )
        runtime.apply_livesplit_update(update(make_snapshot()))
        baseline = (first.resets, second.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_index=1),
                LiveSplitUpdateKind.TRANSITION,
                state_epoch=1,
            )
        )
        self.assertEqual((first.resets, second.resets), (baseline[0], baseline[1] + 1))

    def test_pause_resume_and_timing_only_run_update_keep_rule_state(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        for phase in (TimerPhase.PAUSED, TimerPhase.RUNNING):
            runtime.apply_livesplit_update(
                update(
                    make_snapshot(phase=phase, split_count=1),
                    LiveSplitUpdateKind.TRANSITION,
                )
            )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=1),
                LiveSplitUpdateKind.RUN_CHANGED,
                state_epoch=1,
            )
        )
        self.assertEqual(condition.resets, baseline)

    def test_same_index_transition_restarts_only_that_split_group(self) -> None:
        reset = RecordingCondition(False)
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(first),), (make_rule(second),)), reset_conditions=(reset,)
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        baseline = (reset.resets, first.resets, second.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=2),
                LiveSplitUpdateKind.TRANSITION,
                state_epoch=1,
            )
        )
        self.assertEqual(
            (reset.resets, first.resets, second.resets),
            (baseline[0], baseline[1] + 1, baseline[2]),
        )

    def test_reset_transition_resets_all_rules(self) -> None:
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
                    phase=TimerPhase.NOT_RUNNING, split_index=-1, split_count=1
                ),
                LiveSplitUpdateKind.TRANSITION,
                state_epoch=1,
                transition=LiveSplitTransitionReason.RESET,
            )
        )
        self.assertEqual(
            (reset.resets, main.resets), (baseline[0] + 1, baseline[1] + 1)
        )

    def test_session_change_is_ignored_on_the_current_runtime(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),),)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = condition.resets
        # A different session must never be applied onto the current rules; a
        # fresh runtime is established after reconnecting instead.
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=1),
                LiveSplitUpdateKind.TRANSITION,
                session_id=2,
            )
        )
        self.assertEqual(runtime.current_snapshot, make_snapshot(split_count=1))
        self.assertEqual(condition.resets, baseline)

    def test_structural_run_change_resets_but_timing_change_does_not(self) -> None:
        reset = RecordingCondition(False)
        main = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(main),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = (reset.resets, main.resets)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=1),
                LiveSplitUpdateKind.RUN_CHANGED,
                state_epoch=1,
            )
        )
        self.assertEqual((reset.resets, main.resets), baseline)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=1),
                LiveSplitUpdateKind.RUN_CHANGED,
                state_epoch=2,
                run_structure_changed=True,
            )
        )
        self.assertEqual(
            (reset.resets, main.resets), (baseline[0] + 1, baseline[1] + 1)
        )

    def test_invalid_split_count_recovers_on_structural_run_change(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_scenario(((make_rule(condition),), None, None)))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=3),
                LiveSplitUpdateKind.RUN_CHANGED,
                state_epoch=1,
                run_structure_changed=True,
            )
        )
        self.assertEqual(runtime.evaluate(context()), Action(operation="split"))


class ScenarioRuntimeTimeoutTest(unittest.TestCase):
    def test_same_index_timeout_restarts_only_current_rules_and_allows_new_action(
        self,
    ) -> None:
        reset = RecordingCondition(False)
        condition = RecordingCondition(True)
        other = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(condition),), (make_rule(other),)),
                reset_conditions=(reset,),
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        action = runtime.evaluate(context(10))
        self.assertEqual(action, Action(operation="split"))
        assert action is not None
        runtime.action_accepted(action, 100)
        self.assertEqual(runtime.state_wait_deadline_ns, 1_000_000_100)
        runtime.state_wait_timed_out(1_000_000_100)
        self.assertIsNone(runtime.pending_action)
        self.assertEqual(condition.resets, 2)
        self.assertEqual(other.resets, 1)
        self.assertEqual(reset.resets, 1)
        self.assertEqual(
            runtime.evaluate(context(1_000_000_101)), Action(operation="split")
        )


class ScenarioRuntimePendingResetTest(unittest.TestCase):
    def _runtime_with_split_pending(
        self,
    ) -> tuple[ScenarioRuntime, RecordingCondition]:
        reset = RecordingCondition(False)
        main = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(((make_rule(main),),), reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        self.assertEqual(runtime.evaluate(context()), Action("split"))
        runtime.action_accepted(Action("split"), 1)
        return runtime, main

    def test_rejected_reset_keeps_the_split_wait(self) -> None:
        runtime, _ = self._runtime_with_split_pending()
        runtime.external_action_pending(Action("reset"), 2)
        runtime.action_not_dispatched(Action("reset"))

        self.assertEqual(runtime.pending_action, Action("split"))
        self.assertIsNone(runtime.reset_pending)
        self.assertIsNone(runtime.evaluate(context(3)))

    def test_accepted_reset_survives_a_stale_split_event(self) -> None:
        runtime, _ = self._runtime_with_split_pending()
        runtime.external_action_pending(Action("reset"), 2)
        runtime.action_accepted(Action("reset"), 3)

        self.assertIsNone(runtime.pending_action)
        self.assertEqual(runtime.reset_pending, Action("reset"))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=1),
                LiveSplitUpdateKind.TRANSITION,
                state_epoch=4,
                transition=LiveSplitTransitionReason.SPLIT,
            )
        )
        self.assertEqual(runtime.reset_pending, Action("reset"))

    def test_reset_wait_blocks_a_new_normal_control(self) -> None:
        runtime, _ = self._runtime_with_split_pending()
        runtime.external_action_pending(Action("reset"), 2)
        runtime.action_accepted(Action("reset"), 3)

        self.assertIsNone(runtime.evaluate(context(4)))

    def test_pause_transition_does_not_complete_a_split_wait(self) -> None:
        runtime, _ = self._runtime_with_split_pending()
        runtime.apply_livesplit_update(
            update(
                make_snapshot(phase=TimerPhase.PAUSED, split_count=1),
                LiveSplitUpdateKind.TRANSITION,
                state_epoch=4,
                transition=LiveSplitTransitionReason.PAUSE,
            )
        )
        self.assertEqual(runtime.pending_action, Action("split"))

    def test_run_changed_does_not_clear_a_pending_action(self) -> None:
        runtime, _ = self._runtime_with_split_pending()
        runtime.apply_livesplit_update(
            update(
                make_snapshot(split_count=1),
                LiveSplitUpdateKind.RUN_CHANGED,
                state_epoch=4,
            )
        )
        self.assertEqual(runtime.pending_action, Action("split"))

    def test_reset_transition_releases_the_reset_wait(self) -> None:
        runtime, _ = self._runtime_with_split_pending()
        runtime.external_action_pending(Action("reset"), 2)
        runtime.action_accepted(Action("reset"), 3)
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.NOT_RUNNING,
                    split_index=-1,
                    split_count=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
                state_epoch=4,
                transition=LiveSplitTransitionReason.RESET,
            )
        )
        self.assertIsNone(runtime.reset_pending)


class ScenarioRuntimeRejectedResetTest(unittest.TestCase):
    def test_same_phase_and_index_clears_pending_and_restarts_rules(self) -> None:
        reset = RecordingCondition(False)
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(first),), (make_rule(second),)),
                reset_conditions=(reset,),
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        first.result = True
        self.assertEqual(runtime.evaluate(context()), Action("split"))
        runtime.action_accepted(Action("split"), 1)
        runtime.external_action_pending(Action("reset"), 2)
        baseline = (reset.resets, first.resets, second.resets)

        runtime.settle_rejected_reset(
            update(
                make_snapshot(split_count=2),
                LiveSplitUpdateKind.PERIODIC,
                state_epoch=7,
            )
        )

        self.assertIsNone(runtime.pending_action)
        self.assertIsNone(runtime.reset_pending)
        self.assertEqual(runtime.state_epoch, 7)
        self.assertEqual(
            (reset.resets, first.resets, second.resets),
            (baseline[0] + 1, baseline[1] + 1, baseline[2]),
        )

    def test_advanced_index_restarts_that_index(self) -> None:
        reset = RecordingCondition(False)
        first = RecordingCondition(False)
        second = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario(
                ((make_rule(first),), (make_rule(second),)),
                reset_conditions=(reset,),
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        baseline = (first.resets, second.resets)

        runtime.settle_rejected_reset(
            update(
                make_snapshot(split_count=2, split_index=1),
                LiveSplitUpdateKind.PERIODIC,
                state_epoch=3,
            )
        )

        self.assertEqual((first.resets, second.resets), (baseline[0], baseline[1] + 1))
        self.assertEqual(runtime.evaluate(context()), Action("split"))

    def test_not_running_moves_to_start(self) -> None:
        reset = RecordingCondition(False)
        start = RecordingCondition(True)
        runtime = ScenarioRuntime(
            make_scenario((), start_condition=start, reset_conditions=(reset,))
        )
        runtime.apply_livesplit_update(update(make_snapshot(split_count=1)))
        baseline = (start.resets, reset.resets)

        runtime.settle_rejected_reset(
            update(
                make_snapshot(
                    phase=TimerPhase.NOT_RUNNING,
                    split_index=-1,
                    split_count=1,
                ),
                LiveSplitUpdateKind.PERIODIC,
                state_epoch=2,
            )
        )

        self.assertEqual(
            (start.resets, reset.resets), (baseline[0] + 1, baseline[1] + 1)
        )
        self.assertEqual(runtime.evaluate(context()), Action("start"))


if __name__ == "__main__":
    unittest.main()
