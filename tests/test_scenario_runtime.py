import logging
import unittest
from collections.abc import Callable
from typing import Literal, overload
from unittest.mock import patch

import numpy as np

from divergencesplitter import (
    Action,
    Frame,
    FrameContext,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    MonotonicTime,
    RuleDefinition,
    ScenarioDefinition,
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


def make_action(
    operation: str = "split",
    *,
    scenario_id: str = "scenario",
    target_id: str = "target",
) -> Action:
    return Action(
        scenario_id=scenario_id,
        target_id=target_id,
        operation=operation,
    )


def make_definition(
    rules: dict[int, tuple[RuleDefinition, ...]],
) -> ScenarioDefinition:
    return ScenarioDefinition(scenario_id="scenario", target_id="target", rules=rules)


def make_rule(
    condition: RecordingCondition,
    *,
    action: Action | None = None,
    name: str | None = None,
) -> RuleDefinition:
    return RuleDefinition(
        action=action or make_action(),
        condition_factory=lambda: condition,
        name=name,
    )


def make_snapshot(
    *,
    session_id: int = 1,
    state_revision: int = 0,
    event_sequence: int = 0,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 2,
    target_id: str = "target",
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        target_id=target_id,
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
        frame=Frame(image=np.zeros((1, 1), dtype=np.uint8)),
        now=MonotonicTime(nanoseconds),
    )


class ModelValidationTest(unittest.TestCase):
    def test_snapshot_phase_invariants_are_validated(self) -> None:
        invalid: tuple[Callable[[], LiveSplitSnapshot], ...] = (
            lambda: make_snapshot(phase=TimerPhase.NOT_RUNNING, split_index=0),
            lambda: make_snapshot(phase=TimerPhase.RUNNING, split_index=2),
            lambda: make_snapshot(phase=TimerPhase.PAUSED, split_count=0),
            lambda: make_snapshot(
                phase=TimerPhase.ENDED,
                split_index=0,
                split_count=0,
            ),
        )
        for factory in invalid:
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()

        snapshot = make_snapshot(
            phase=TimerPhase.NOT_RUNNING,
            split_index=-1,
            split_count=0,
        )
        self.assertEqual(snapshot.split_count, 0)

    def test_scenario_definition_defensively_copies_rules(self) -> None:
        condition = RecordingCondition(False)
        source = {0: (make_rule(condition),)}
        definition = ScenarioDefinition(
            scenario_id="scenario",
            target_id="target",
            rules=source,
        )
        source[0] = ()
        source[1] = ()
        self.assertEqual(len(definition.rules[0]), 1)
        self.assertNotIn(1, definition.rules)

    def test_rule_definition_captures_source_and_normalizes_empty_name(self) -> None:
        definition = make_rule(RecordingCondition(False), name="")
        self.assertIsNone(definition.name)
        self.assertTrue(
            definition.source_path.endswith("tests/test_scenario_runtime.py")
        )
        self.assertGreater(definition.source_line, 0)

    def test_rule_definition_falls_back_when_source_is_unavailable(self) -> None:
        with patch(
            "divergencesplitter.models.inspect.currentframe",
            return_value=None,
        ):
            definition = make_rule(RecordingCondition(False))
        self.assertEqual(
            (definition.source_path, definition.source_line),
            ("<unknown>", 0),
        )

    def test_action_rejects_unsupported_operation(self) -> None:
        with self.assertRaises(ValueError):
            make_action("start")


class ScenarioRuntimeEvaluationTest(unittest.TestCase):
    def test_does_not_evaluate_or_reset_before_initial_snapshot(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_definition({0: (make_rule(condition),)}))
        self.assertIsNone(runtime.evaluate(context()))
        self.assertEqual((condition.calls, condition.resets), (0, 0))

    def test_evaluates_current_split_in_order_and_stops_at_first_action(self) -> None:
        first = RecordingCondition(False)
        second = RecordingCondition(True)
        third = RecordingCondition(True)
        second_action = make_action("skip")
        runtime = ScenarioRuntime(
            make_definition(
                {
                    0: (
                        make_rule(first),
                        make_rule(second, action=second_action),
                        make_rule(third),
                    )
                }
            )
        )
        runtime.apply_livesplit_update(update(make_snapshot()))
        self.assertIs(runtime.evaluate(context()), second_action)
        self.assertEqual((first.calls, second.calls, third.calls), (1, 1, 0))

    def test_rule_exception_and_logging_failure_do_not_stop_later_rule(self) -> None:
        failing = RecordingCondition(False, error=RuntimeError("condition failed"))
        succeeding = RecordingCondition(True)
        logger = logging.getLogger(f"raising.{self.id()}")
        logger.handlers.clear()
        logger.propagate = False
        logger.addHandler(RaisingHandler())
        runtime = ScenarioRuntime(
            make_definition({0: (make_rule(failing), make_rule(succeeding))}),
            logger=logger,
        )
        runtime.apply_livesplit_update(update(make_snapshot()))
        self.assertIsNotNone(runtime.evaluate(context()))
        self.assertEqual((failing.calls, succeeding.calls), (1, 1))

    def test_action_identifiers_must_match_scenario(self) -> None:
        condition = RecordingCondition(False)
        with self.assertRaises(ValueError):
            ScenarioRuntime(
                make_definition(
                    {
                        0: (
                            make_rule(
                                condition,
                                action=make_action(scenario_id="other"),
                            ),
                        )
                    }
                )
            )


class ScenarioRuntimeUpdateTest(unittest.TestCase):
    def test_periodic_duplicate_and_reversed_updates_do_not_reset(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_definition({0: (make_rule(condition),)}))
        runtime.apply_livesplit_update(update(make_snapshot(event_sequence=2)))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=3),
                LiveSplitUpdateKind.PERIODIC,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=3),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(event_sequence=1),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(condition.resets, 0)
        runtime.evaluate(context())
        self.assertEqual(condition.calls, 1)

    def test_periodic_state_change_requires_resync(self) -> None:
        condition = RecordingCondition(False)
        runtime = ScenarioRuntime(make_definition({0: (make_rule(condition),)}))
        runtime.apply_livesplit_update(update(make_snapshot()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(state_revision=1, event_sequence=1),
                LiveSplitUpdateKind.PERIODIC,
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        self.assertEqual(condition.calls, 0)

    def test_transition_resets_only_destination_and_same_index_counts(self) -> None:
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_definition({0: (make_rule(first),), 1: (make_rule(second),)})
        )
        runtime.apply_livesplit_update(update(make_snapshot()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    state_revision=1,
                    event_sequence=1,
                    split_index=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual((first.resets, second.resets), (0, 1))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    state_revision=2,
                    event_sequence=2,
                    split_index=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual((first.resets, second.resets), (0, 2))

    def test_ended_does_not_evaluate_and_undo_resets_last_split(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_definition({1: (make_rule(condition),)}))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.ENDED,
                    split_index=2,
                    state_revision=2,
                )
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    phase=TimerPhase.RUNNING,
                    split_index=1,
                    state_revision=3,
                    event_sequence=1,
                ),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertEqual(condition.resets, 1)
        self.assertIsNotNone(runtime.evaluate(context()))

    def test_gap_waits_for_resync_and_revision_controls_reset(self) -> None:
        unchanged = RecordingCondition(False)
        runtime = ScenarioRuntime(make_definition({0: (make_rule(unchanged),)}))
        runtime.apply_livesplit_update(
            update(make_snapshot(state_revision=4, event_sequence=1))
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(state_revision=4, event_sequence=3),
                LiveSplitUpdateKind.PERIODIC,
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(state_revision=4, event_sequence=3),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(unchanged.resets, 0)
        runtime.evaluate(context())
        self.assertEqual(unchanged.calls, 1)

        advanced = RecordingCondition(False)
        runtime = ScenarioRuntime(make_definition({0: (make_rule(advanced),)}))
        runtime.apply_livesplit_update(
            update(make_snapshot(state_revision=4, event_sequence=1))
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(state_revision=5, event_sequence=3),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        runtime.apply_livesplit_update(
            update(
                make_snapshot(state_revision=5, event_sequence=3),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual(advanced.resets, 1)

    def test_session_resync_resets_all_rules(self) -> None:
        first = RecordingCondition(False)
        second = RecordingCondition(False)
        runtime = ScenarioRuntime(
            make_definition({0: (make_rule(first),), 1: (make_rule(second),)})
        )
        runtime.apply_livesplit_update(update(make_snapshot(event_sequence=5)))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(session_id=2, event_sequence=0),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(session_id=2, event_sequence=0),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertEqual((first.resets, second.resets), (1, 1))

    def test_invalid_split_count_stops_until_valid_resync(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_definition({2: (make_rule(condition),)}))
        runtime.apply_livesplit_update(update(make_snapshot(split_count=2)))
        self.assertIsNone(runtime.evaluate(context()))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(
                    split_index=2,
                    split_count=3,
                    event_sequence=1,
                ),
                LiveSplitUpdateKind.RESYNC,
            )
        )
        self.assertIsNotNone(runtime.evaluate(context()))


class ScenarioRuntimeTimeoutTest(unittest.TestCase):
    def test_timeout_waits_until_boundary_then_resets_and_restarts(self) -> None:
        condition = RecordingCondition(True)
        action = make_action()
        runtime = ScenarioRuntime(
            make_definition({0: (make_rule(condition, action=action),)})
        )
        runtime.apply_livesplit_update(update(make_snapshot()))
        self.assertIs(runtime.evaluate(context(10)), action)
        self.assertIsNone(runtime.evaluate(context(1_000_000_009)))
        self.assertEqual(condition.resets, 0)
        self.assertIs(runtime.evaluate(context(1_000_000_010)), action)
        self.assertEqual(condition.resets, 1)

    def test_transition_applied_at_timeout_boundary_takes_priority(self) -> None:
        condition = RecordingCondition(True)
        runtime = ScenarioRuntime(make_definition({0: (make_rule(condition),)}))
        runtime.apply_livesplit_update(update(make_snapshot()))
        runtime.evaluate(context(0))
        runtime.apply_livesplit_update(
            update(
                make_snapshot(state_revision=1, event_sequence=1),
                LiveSplitUpdateKind.TRANSITION,
            )
        )
        self.assertIsNotNone(runtime.evaluate(context(1_000_000_000)))
        self.assertEqual(condition.resets, 1)


if __name__ == "__main__":
    unittest.main()
