import unittest
from typing import Literal, cast, overload

import numpy as np

from divergencesplitter.condition import (
    All,
    Any,
    Detected,
    Elapsed,
    FallingEdge,
    Hold,
    Not,
    Nth,
    Once,
    RisingEdge,
    Then,
)
from divergencesplitter.models import (
    DetectionResult,
    Frame,
    FrameContext,
    MonotonicTime,
)


def make_context(nanoseconds: int = 0) -> FrameContext:
    return FrameContext(
        frame=Frame(image=np.zeros((1,), dtype=np.uint8)),
        now=MonotonicTime(nanoseconds=nanoseconds),
    )


class SequenceCondition:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[bool] = []
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
        self.calls.append(is_short_circuited)
        return cast("bool | None", self.results.pop(0))

    def reset(self) -> None:
        self.resets += 1


class CountingDetector:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls = 0

    def detect(self, context: FrameContext) -> DetectionResult:
        self.calls += 1
        return DetectionResult(score=self.score)


class BooleanConditionTest(unittest.TestCase):
    def test_empty_identities(self) -> None:
        self.assertTrue(All().evaluate(make_context()))
        self.assertFalse(Any().evaluate(make_context()))

    def test_all_short_circuits_remaining_children(self) -> None:
        first = SequenceCondition(False)
        second = SequenceCondition(None)
        self.assertFalse(All(first, second).evaluate(make_context()))
        self.assertEqual(first.calls, [False])
        self.assertEqual(second.calls, [True])

    def test_all_returns_true_when_every_child_is_true(self) -> None:
        self.assertTrue(
            All(SequenceCondition(True), SequenceCondition(True)).evaluate(
                make_context()
            )
        )

    def test_any_short_circuits_remaining_children(self) -> None:
        first = SequenceCondition(True)
        second = SequenceCondition(None)
        self.assertTrue(Any(first, second).evaluate(make_context()))
        self.assertEqual(first.calls, [False])
        self.assertEqual(second.calls, [True])

    def test_any_returns_false_when_every_child_is_false(self) -> None:
        self.assertFalse(
            Any(SequenceCondition(False), SequenceCondition(False)).evaluate(
                make_context()
            )
        )

    def test_parent_short_circuit_propagates_to_all_children(self) -> None:
        first = SequenceCondition(None)
        second = SequenceCondition(True)
        self.assertIsNone(
            All(first, second).evaluate(make_context(), is_short_circuited=True)
        )
        self.assertEqual(first.calls, [True])
        self.assertEqual(second.calls, [True])

    def test_not_inverts_and_propagates_short_circuit(self) -> None:
        child = SequenceCondition(False, None)
        condition = Not(child)
        self.assertTrue(condition.evaluate(make_context()))
        self.assertIsNone(condition.evaluate(make_context(), is_short_circuited=True))
        self.assertEqual(child.calls, [False, True])

    def test_rejects_invalid_normal_child_result(self) -> None:
        with self.assertRaises(TypeError):
            All(SequenceCondition(None)).evaluate(make_context())

    def test_rejects_invalid_short_child_result(self) -> None:
        with self.assertRaises(TypeError):
            All(SequenceCondition(False), SequenceCondition(1)).evaluate(make_context())

    def test_reset_propagates_to_children(self) -> None:
        first = SequenceCondition(True)
        second = SequenceCondition(True)
        All(first, second).reset()
        self.assertEqual((first.resets, second.resets), (1, 1))


class EdgeConditionTest(unittest.TestCase):
    def test_rising_edge_uses_first_observation_as_baseline(self) -> None:
        condition = RisingEdge(SequenceCondition(False, False, True, True))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertFalse(condition.evaluate(make_context()))

    def test_falling_edge_uses_first_observation_as_baseline(self) -> None:
        condition = FallingEdge(SequenceCondition(True, True, False, False))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertFalse(condition.evaluate(make_context()))

    def test_short_circuited_edge_updates_state(self) -> None:
        child = SequenceCondition(False, True)
        condition = RisingEdge(child)
        self.assertIsNone(condition.evaluate(make_context(), is_short_circuited=True))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertEqual(child.calls, [False, False])

    def test_reset_restores_baseline_and_resets_child(self) -> None:
        child = SequenceCondition(False, True, True)
        condition = RisingEdge(child)
        condition.evaluate(make_context())
        self.assertTrue(condition.evaluate(make_context()))
        condition.reset()
        self.assertFalse(condition.evaluate(make_context()))
        self.assertEqual(child.resets, 1)


class HoldConditionTest(unittest.TestCase):
    def test_fires_at_inclusive_duration_boundary(self) -> None:
        condition = Hold(SequenceCondition(True, True, True), 5)
        self.assertFalse(condition.evaluate(make_context(10)))
        self.assertFalse(condition.evaluate(make_context(14)))
        self.assertTrue(condition.evaluate(make_context(15)))

    def test_false_restarts_duration(self) -> None:
        condition = Hold(SequenceCondition(True, False, True, True), 5)
        self.assertFalse(condition.evaluate(make_context(0)))
        self.assertFalse(condition.evaluate(make_context(10)))
        self.assertFalse(condition.evaluate(make_context(15)))
        self.assertTrue(condition.evaluate(make_context(20)))

    def test_zero_duration_fires_on_first_true(self) -> None:
        self.assertTrue(Hold(SequenceCondition(True), 0).evaluate(make_context()))

    def test_short_circuited_hold_updates_state(self) -> None:
        child = SequenceCondition(True, True)
        condition = Hold(child, 5)
        self.assertIsNone(condition.evaluate(make_context(0), is_short_circuited=True))
        self.assertTrue(condition.evaluate(make_context(5)))
        self.assertEqual(child.calls, [False, False])

    def test_rejects_invalid_duration(self) -> None:
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Hold(SequenceCondition(True), cast("int", value))

    def test_rejects_backwards_time_while_active(self) -> None:
        condition = Hold(SequenceCondition(True, True), 5)
        condition.evaluate(make_context(10))
        with self.assertRaises(ValueError):
            condition.evaluate(make_context(9))

    def test_instances_do_not_share_state(self) -> None:
        first = Hold(SequenceCondition(True, True), 5)
        second = Hold(SequenceCondition(True), 5)
        first.evaluate(make_context(0))
        self.assertTrue(first.evaluate(make_context(5)))
        self.assertFalse(second.evaluate(make_context(5)))


class ThenConditionTest(unittest.TestCase):
    def test_advances_at_most_one_stage_per_frame(self) -> None:
        first = SequenceCondition(True, None)
        second = SequenceCondition(None, True)
        condition = Then(first, second, within_nanoseconds=5)
        self.assertFalse(condition.evaluate(make_context(0)))
        self.assertTrue(condition.evaluate(make_context(5)))
        self.assertEqual(first.calls, [False, True])
        self.assertEqual(second.calls, [True, False])

    def test_deadline_is_inclusive(self) -> None:
        condition = Then(
            SequenceCondition(True, None),
            SequenceCondition(None, True),
            within_nanoseconds=5,
        )
        self.assertFalse(condition.evaluate(make_context(0)))
        self.assertTrue(condition.evaluate(make_context(5)))

    def test_expired_attempt_restarts_on_same_frame(self) -> None:
        first = SequenceCondition(True, True, None)
        second = SequenceCondition(None, None, True)
        condition = Then(first, second, within_nanoseconds=5)
        self.assertFalse(condition.evaluate(make_context(0)))
        self.assertFalse(condition.evaluate(make_context(6)))
        self.assertTrue(condition.evaluate(make_context(11)))

    def test_completed_then_keeps_children_updated(self) -> None:
        first = SequenceCondition(True, None, None)
        second = SequenceCondition(None, True, None)
        condition = Then(first, second, within_nanoseconds=5)
        condition.evaluate(make_context(0))
        self.assertTrue(condition.evaluate(make_context(1)))
        self.assertTrue(condition.evaluate(make_context(2)))
        self.assertEqual(first.calls, [False, True, True])
        self.assertEqual(second.calls, [True, False, True])

    def test_short_circuited_then_advances_state(self) -> None:
        condition = Then(
            SequenceCondition(True, None),
            SequenceCondition(None, True),
            within_nanoseconds=5,
        )
        self.assertIsNone(condition.evaluate(make_context(0), is_short_circuited=True))
        self.assertTrue(condition.evaluate(make_context(5)))

    def test_single_child_completes_without_waiting(self) -> None:
        condition = Then(SequenceCondition(True), within_nanoseconds=0)
        self.assertTrue(condition.evaluate(make_context()))

    def test_rejects_backwards_time_while_in_progress(self) -> None:
        condition = Then(
            SequenceCondition(True, None),
            SequenceCondition(None, True),
            within_nanoseconds=5,
        )
        condition.evaluate(make_context(10))
        with self.assertRaises(ValueError):
            condition.evaluate(make_context(9))

    def test_reset_restarts_progress_and_resets_children(self) -> None:
        first = SequenceCondition(True, True)
        second = SequenceCondition(None, None)
        condition = Then(first, second, within_nanoseconds=5)
        condition.evaluate(make_context(0))
        condition.reset()
        self.assertFalse(condition.evaluate(make_context(10)))
        self.assertEqual((first.resets, second.resets), (1, 1))

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            Then(within_nanoseconds=0)
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Then(SequenceCondition(True), within_nanoseconds=cast("int", value))


class OnceConditionTest(unittest.TestCase):
    def test_latches_and_stops_evaluating_child(self) -> None:
        child = SequenceCondition(False, True)
        condition = Once(child)
        self.assertFalse(condition.evaluate(make_context()))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertEqual(len(child.calls), 2)

    def test_short_circuited_once_latches_without_replay(self) -> None:
        child = SequenceCondition(True)
        condition = Once(child)
        self.assertIsNone(condition.evaluate(make_context(), is_short_circuited=True))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertEqual(len(child.calls), 1)

    def test_reset_resumes_child_evaluation(self) -> None:
        child = SequenceCondition(True, False)
        condition = Once(child)
        condition.evaluate(make_context())
        condition.reset()
        self.assertFalse(condition.evaluate(make_context()))
        self.assertEqual(child.resets, 1)


class NthConditionTest(unittest.TestCase):
    def test_counts_only_true_and_fires_once(self) -> None:
        child = SequenceCondition(True, False, True)
        condition = Nth(child, 2)
        self.assertFalse(condition.evaluate(make_context()))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertTrue(condition.evaluate(make_context()))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertEqual(len(child.calls), 3)

    def test_count_one_fires_on_first_true(self) -> None:
        self.assertTrue(Nth(SequenceCondition(True), 1).evaluate(make_context()))

    def test_counts_true_on_consecutive_frames(self) -> None:
        condition = Nth(SequenceCondition(True, True), 2)
        self.assertFalse(condition.evaluate(make_context()))
        self.assertTrue(condition.evaluate(make_context()))

    def test_short_circuited_match_is_not_replayed(self) -> None:
        child = SequenceCondition(True)
        condition = Nth(child, 1)
        self.assertIsNone(condition.evaluate(make_context(), is_short_circuited=True))
        self.assertFalse(condition.evaluate(make_context()))
        self.assertEqual(len(child.calls), 1)

    def test_reset_restarts_counting(self) -> None:
        child = SequenceCondition(True, True)
        condition = Nth(child, 1)
        condition.evaluate(make_context())
        condition.reset()
        self.assertTrue(condition.evaluate(make_context()))
        self.assertEqual(child.resets, 1)

    def test_rejects_invalid_count(self) -> None:
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Nth(SequenceCondition(True), cast("int", value))


class ElapsedConditionTest(unittest.TestCase):
    def test_fires_at_inclusive_boundary_and_latches(self) -> None:
        condition = Elapsed(5)
        self.assertFalse(condition.evaluate(make_context(10)))
        self.assertFalse(condition.evaluate(make_context(14)))
        self.assertTrue(condition.evaluate(make_context(15)))
        self.assertTrue(condition.evaluate(make_context(16)))

    def test_zero_duration_fires_on_first_evaluation(self) -> None:
        self.assertTrue(Elapsed(0).evaluate(make_context(10)))

    def test_short_circuit_starts_timer(self) -> None:
        condition = Elapsed(5)
        self.assertIsNone(condition.evaluate(make_context(10), is_short_circuited=True))
        self.assertTrue(condition.evaluate(make_context(15)))

    def test_zero_duration_can_complete_while_short_circuited(self) -> None:
        condition = Elapsed(0)
        self.assertIsNone(condition.evaluate(make_context(), is_short_circuited=True))
        self.assertTrue(condition.evaluate(make_context()))

    def test_reset_uses_next_evaluation_as_new_origin(self) -> None:
        condition = Elapsed(5)
        condition.evaluate(make_context(0))
        condition.reset()
        self.assertFalse(condition.evaluate(make_context(10)))
        self.assertTrue(condition.evaluate(make_context(15)))

    def test_rejects_invalid_duration(self) -> None:
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Elapsed(cast("int", value))

    def test_rejects_backwards_time_while_active(self) -> None:
        condition = Elapsed(5)
        condition.evaluate(make_context(10))
        with self.assertRaises(ValueError):
            condition.evaluate(make_context(9))


class DetectedConditionTest(unittest.TestCase):
    def test_threshold_is_inclusive(self) -> None:
        self.assertFalse(Detected(CountingDetector(0.4), 0.5).evaluate(make_context()))
        self.assertTrue(Detected(CountingDetector(0.5), 0.5).evaluate(make_context()))
        self.assertTrue(Detected(CountingDetector(0.6), 0.5).evaluate(make_context()))

    def test_short_circuit_skips_detector(self) -> None:
        detector = CountingDetector(1.0)
        self.assertIsNone(
            Detected(detector, 0.5).evaluate(make_context(), is_short_circuited=True)
        )
        self.assertEqual(detector.calls, 0)

    def test_equivalent_detected_conditions_use_detector_cache(self) -> None:
        detector = CountingDetector(0.7)
        context = make_context()
        self.assertTrue(Detected(detector, 0.5).evaluate(context))
        self.assertFalse(Detected(detector, 0.8).evaluate(context))
        self.assertEqual(detector.calls, 1)

    def test_reset_does_not_clear_detector_cache(self) -> None:
        detector = CountingDetector(0.7)
        context = make_context()
        condition = Detected(detector, 0.5)
        self.assertTrue(condition.evaluate(context))
        condition.reset()
        self.assertTrue(condition.evaluate(context))
        self.assertEqual(detector.calls, 1)


if __name__ == "__main__":
    unittest.main()
