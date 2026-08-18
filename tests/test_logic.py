import unittest

from divergencesplitter.logic import (
    All,
    Any,
    FallingEdge,
    Hold,
    Not,
    RisingEdge,
    Then,
)
from divergencesplitter.models import MonotonicTime


def t(nanoseconds: int) -> MonotonicTime:
    return MonotonicTime(nanoseconds=nanoseconds)


class AllTest(unittest.TestCase):
    def test_empty_is_true(self):
        self.assertTrue(All().apply([]))

    def test_all_true(self):
        self.assertTrue(All().apply([True, True, True]))

    def test_any_false(self):
        self.assertFalse(All().apply([True, False, True]))

    def test_all_false(self):
        self.assertFalse(All().apply([False, False]))


class AnyTest(unittest.TestCase):
    def test_empty_is_false(self):
        self.assertFalse(Any().apply([]))

    def test_any_true(self):
        self.assertTrue(Any().apply([False, False, True]))

    def test_all_false(self):
        self.assertFalse(Any().apply([False, False]))


class NotTest(unittest.TestCase):
    def test_negation(self):
        self.assertFalse(Not().apply(True))
        self.assertTrue(Not().apply(False))


class RisingEdgeTest(unittest.TestCase):
    def test_baseline_and_transitions(self):
        edge = RisingEdge()
        self.assertFalse(edge.step(True))
        self.assertFalse(edge.step(True))
        self.assertFalse(edge.step(False))
        self.assertTrue(edge.step(True))
        self.assertFalse(edge.step(False))
        self.assertTrue(edge.step(True))

    def test_new_instance_resets_baseline(self):
        edge = RisingEdge()
        self.assertFalse(edge.step(False))
        self.assertTrue(edge.step(True))
        edge = RisingEdge()
        self.assertFalse(edge.step(True))
        self.assertFalse(edge.step(False))
        self.assertTrue(edge.step(True))


class FallingEdgeTest(unittest.TestCase):
    def test_baseline_and_transitions(self):
        edge = FallingEdge()
        self.assertFalse(edge.step(False))
        self.assertFalse(edge.step(False))
        self.assertFalse(edge.step(True))
        self.assertTrue(edge.step(False))
        self.assertFalse(edge.step(True))
        self.assertTrue(edge.step(False))

    def test_new_instance_resets_baseline(self):
        edge = FallingEdge()
        self.assertFalse(edge.step(True))
        self.assertTrue(edge.step(False))
        edge = FallingEdge()
        self.assertFalse(edge.step(False))
        self.assertFalse(edge.step(True))
        self.assertTrue(edge.step(False))


class HoldTest(unittest.TestCase):
    def test_start_before_and_satisfied(self):
        hold = Hold(duration_nanoseconds=10)
        self.assertFalse(hold.step(True, t(0)))
        self.assertFalse(hold.step(True, t(9)))
        self.assertTrue(hold.step(True, t(10)))
        self.assertTrue(hold.step(True, t(20)))

    def test_release_and_rearm(self):
        hold = Hold(duration_nanoseconds=10)
        self.assertFalse(hold.step(True, t(0)))
        self.assertFalse(hold.step(False, t(5)))
        self.assertFalse(hold.step(True, t(6)))
        self.assertTrue(hold.step(True, t(16)))

    def test_zero_duration_satisfied_immediately(self):
        hold = Hold(duration_nanoseconds=0)
        self.assertTrue(hold.step(True, t(0)))

    def test_backward_time_raises(self):
        hold = Hold(duration_nanoseconds=10)
        self.assertFalse(hold.step(True, t(10)))
        with self.assertRaises(ValueError):
            hold.step(True, t(5))

    def test_negative_duration_rejected(self):
        with self.assertRaises(ValueError):
            Hold(duration_nanoseconds=-1)

    def test_independent_instances_do_not_interfere(self):
        hold_a = Hold(duration_nanoseconds=10)
        hold_b = Hold(duration_nanoseconds=10)
        self.assertFalse(hold_a.step(True, t(0)))
        self.assertFalse(hold_b.step(False, t(0)))
        self.assertTrue(hold_a.step(True, t(10)))
        self.assertFalse(hold_b.step(True, t(10)))
        self.assertTrue(hold_b.step(True, t(20)))


class ThenTest(unittest.TestCase):
    def test_conditions_must_be_satisfied_in_order(self):
        then = Then(step_count=3, within_nanoseconds=1000)
        self.assertFalse(then.step([False, True, True], t(0)))
        self.assertFalse(then.step([True, False, False], t(1)))
        self.assertFalse(then.step([False, True, True], t(2)))
        self.assertTrue(then.step([False, False, True], t(3)))

    def test_advances_at_most_one_stage_per_call(self):
        then = Then(step_count=3, within_nanoseconds=1000)
        self.assertFalse(then.step([True, True, True], t(0)))
        self.assertFalse(then.step([True, True, True], t(1)))
        self.assertTrue(then.step([True, True, True], t(2)))

    def test_deadline_is_inclusive(self):
        then = Then(step_count=2, within_nanoseconds=100)
        self.assertFalse(then.step([True, False], t(0)))
        self.assertTrue(then.step([False, True], t(100)))

    def test_deadline_exceeded_restarts_from_first_condition(self):
        then = Then(step_count=2, within_nanoseconds=100)
        self.assertFalse(then.step([True, False], t(0)))
        self.assertFalse(then.step([True, False], t(101)))
        self.assertTrue(then.step([False, True], t(200)))

    def test_deadline_exceeded_without_first_condition_returns_to_idle(self):
        then = Then(step_count=2, within_nanoseconds=100)
        self.assertFalse(then.step([True, False], t(0)))
        self.assertFalse(then.step([False, True], t(101)))
        self.assertFalse(then.step([True, False], t(200)))
        self.assertTrue(then.step([False, True], t(250)))

    def test_step_count_one_completes_immediately(self):
        then = Then(step_count=1, within_nanoseconds=0)
        self.assertFalse(then.step([False], t(0)))
        self.assertTrue(then.step([True], t(1)))

    def test_completion_latches_until_new_instance(self):
        then = Then(step_count=1, within_nanoseconds=0)
        self.assertTrue(then.step([True], t(0)))
        self.assertTrue(then.step([False], t(100)))
        then = Then(step_count=1, within_nanoseconds=0)
        self.assertTrue(then.step([True], t(200)))
        self.assertTrue(then.step([False], t(300)))

    def test_backward_time_raises(self):
        then = Then(step_count=2, within_nanoseconds=1000)
        self.assertFalse(then.step([True, False], t(100)))
        with self.assertRaises(ValueError):
            then.step([False, True], t(50))

    def test_input_length_mismatch_raises(self):
        then = Then(step_count=2, within_nanoseconds=100)
        with self.assertRaises(ValueError):
            then.step([True], t(0))
        with self.assertRaises(ValueError):
            then.step([True, False, True], t(0))

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError):
            Then(step_count=0, within_nanoseconds=0)
        with self.assertRaises(ValueError):
            Then(step_count=1, within_nanoseconds=-1)

    def test_independent_instances_do_not_interfere(self):
        then_a = Then(step_count=2, within_nanoseconds=1000)
        then_b = Then(step_count=2, within_nanoseconds=1000)
        self.assertFalse(then_a.step([True, False], t(0)))
        self.assertFalse(then_b.step([False, False], t(0)))
        self.assertTrue(then_a.step([False, True], t(6)))
        self.assertFalse(then_b.step([True, False], t(10)))


if __name__ == "__main__":
    unittest.main()
