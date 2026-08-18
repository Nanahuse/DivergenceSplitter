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
        state = edge.initial_state()
        out, state = edge.step(True, state)
        self.assertFalse(out)
        out, state = edge.step(True, state)
        self.assertFalse(out)
        out, state = edge.step(False, state)
        self.assertFalse(out)
        out, state = edge.step(True, state)
        self.assertTrue(out)
        out, state = edge.step(False, state)
        self.assertFalse(out)
        out, state = edge.step(True, state)
        self.assertTrue(out)

    def test_reactivation_resets_baseline(self):
        edge = RisingEdge()
        state = edge.initial_state()
        _, state = edge.step(False, state)
        out, state = edge.step(True, state)
        self.assertTrue(out)
        state = edge.initial_state()
        out, state = edge.step(True, state)
        self.assertFalse(out)
        out, state = edge.step(False, state)
        self.assertFalse(out)
        out, state = edge.step(True, state)
        self.assertTrue(out)


class FallingEdgeTest(unittest.TestCase):
    def test_baseline_and_transitions(self):
        edge = FallingEdge()
        state = edge.initial_state()
        out, state = edge.step(False, state)
        self.assertFalse(out)
        out, state = edge.step(False, state)
        self.assertFalse(out)
        out, state = edge.step(True, state)
        self.assertFalse(out)
        out, state = edge.step(False, state)
        self.assertTrue(out)
        out, state = edge.step(True, state)
        self.assertFalse(out)
        out, state = edge.step(False, state)
        self.assertTrue(out)

    def test_reactivation_resets_baseline(self):
        edge = FallingEdge()
        state = edge.initial_state()
        _, state = edge.step(True, state)
        out, state = edge.step(False, state)
        self.assertTrue(out)
        state = edge.initial_state()
        out, state = edge.step(False, state)
        self.assertFalse(out)
        out, state = edge.step(True, state)
        self.assertFalse(out)
        out, state = edge.step(False, state)
        self.assertTrue(out)


class HoldTest(unittest.TestCase):
    def test_start_before_and_satisfied(self):
        hold = Hold(duration_nanoseconds=10)
        state = hold.initial_state()
        out, state = hold.step(True, t(0), state)
        self.assertFalse(out)
        out, state = hold.step(True, t(9), state)
        self.assertFalse(out)
        out, state = hold.step(True, t(10), state)
        self.assertTrue(out)
        out, state = hold.step(True, t(20), state)
        self.assertTrue(out)

    def test_release_and_rearm(self):
        hold = Hold(duration_nanoseconds=10)
        state = hold.initial_state()
        out, state = hold.step(True, t(0), state)
        self.assertFalse(out)
        out, state = hold.step(False, t(5), state)
        self.assertFalse(out)
        out, state = hold.step(True, t(6), state)
        self.assertFalse(out)
        out, state = hold.step(True, t(16), state)
        self.assertTrue(out)

    def test_zero_duration_satisfied_immediately(self):
        hold = Hold(duration_nanoseconds=0)
        state = hold.initial_state()
        out, state = hold.step(True, t(0), state)
        self.assertTrue(out)

    def test_backward_time_raises(self):
        hold = Hold(duration_nanoseconds=10)
        state = hold.initial_state()
        _, state = hold.step(True, t(10), state)
        with self.assertRaises(ValueError):
            hold.step(True, t(5), state)

    def test_negative_duration_rejected(self):
        with self.assertRaises(ValueError):
            Hold(duration_nanoseconds=-1)

    def test_independent_states_do_not_interfere(self):
        hold = Hold(duration_nanoseconds=10)
        state_a = hold.initial_state()
        state_b = hold.initial_state()
        out_a, state_a = hold.step(True, t(0), state_a)
        out_b, state_b = hold.step(False, t(0), state_b)
        self.assertFalse(out_a)
        self.assertFalse(out_b)
        out_a, state_a = hold.step(True, t(10), state_a)
        self.assertTrue(out_a)
        out_b, state_b = hold.step(True, t(10), state_b)
        self.assertFalse(out_b)
        out_b, state_b = hold.step(True, t(20), state_b)
        self.assertTrue(out_b)


class ThenTest(unittest.TestCase):
    def test_conditions_must_be_satisfied_in_order(self):
        then = Then(step_count=3, within_nanoseconds=1000)
        state = then.initial_state()
        out, state = then.step([False, True, True], t(0), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 0)
        self.assertIsNone(state.start)
        out, state = then.step([True, False, False], t(1), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 1)
        out, state = then.step([False, True, True], t(2), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 2)
        out, state = then.step([False, False, True], t(3), state)
        self.assertTrue(out)

    def test_advances_at_most_one_stage_per_call(self):
        then = Then(step_count=3, within_nanoseconds=1000)
        state = then.initial_state()
        out, state = then.step([True, True, True], t(0), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 1)
        out, state = then.step([True, True, True], t(1), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 2)
        out, state = then.step([True, True, True], t(2), state)
        self.assertTrue(out)

    def test_deadline_is_inclusive(self):
        then = Then(step_count=2, within_nanoseconds=100)
        state = then.initial_state()
        out, state = then.step([True, False], t(0), state)
        self.assertFalse(out)
        out, state = then.step([False, True], t(100), state)
        self.assertTrue(out)

    def test_deadline_exceeded_restarts_from_first_condition(self):
        then = Then(step_count=2, within_nanoseconds=100)
        state = then.initial_state()
        out, state = then.step([True, False], t(0), state)
        self.assertFalse(out)
        out, state = then.step([True, False], t(101), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 1)
        self.assertEqual(state.start, t(101))
        out, state = then.step([False, True], t(200), state)
        self.assertTrue(out)

    def test_deadline_exceeded_without_first_condition_returns_to_idle(self):
        then = Then(step_count=2, within_nanoseconds=100)
        state = then.initial_state()
        _, state = then.step([True, False], t(0), state)
        out, state = then.step([False, True], t(101), state)
        self.assertFalse(out)
        self.assertEqual(state.stage, 0)
        self.assertIsNone(state.start)

    def test_step_count_one_completes_immediately(self):
        then = Then(step_count=1, within_nanoseconds=0)
        state = then.initial_state()
        out, state = then.step([False], t(0), state)
        self.assertFalse(out)
        out, state = then.step([True], t(1), state)
        self.assertTrue(out)

    def test_completion_latches_until_reactivation(self):
        then = Then(step_count=1, within_nanoseconds=0)
        state = then.initial_state()
        out, state = then.step([True], t(0), state)
        self.assertTrue(out)
        out, state = then.step([False], t(100), state)
        self.assertTrue(out)
        state = then.initial_state()
        out, state = then.step([True], t(200), state)
        self.assertTrue(out)
        out, state = then.step([False], t(300), state)
        self.assertTrue(out)

    def test_backward_time_raises(self):
        then = Then(step_count=2, within_nanoseconds=1000)
        state = then.initial_state()
        _, state = then.step([True, False], t(100), state)
        with self.assertRaises(ValueError):
            then.step([False, True], t(50), state)

    def test_input_length_mismatch_raises(self):
        then = Then(step_count=2, within_nanoseconds=100)
        with self.assertRaises(ValueError):
            then.step([True], t(0), then.initial_state())
        with self.assertRaises(ValueError):
            then.step([True, False, True], t(0), then.initial_state())

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError):
            Then(step_count=0, within_nanoseconds=0)
        with self.assertRaises(ValueError):
            Then(step_count=1, within_nanoseconds=-1)

    def test_independent_states_do_not_interfere(self):
        then = Then(step_count=2, within_nanoseconds=1000)
        state_a = then.initial_state()
        state_b = then.initial_state()
        _, state_a = then.step([True, False], t(0), state_a)
        self.assertEqual(state_a.stage, 1)
        self.assertEqual(state_b.stage, 0)
        self.assertIsNone(state_b.start)
        out_b, state_b = then.step([True, False], t(5), state_b)
        self.assertFalse(out_b)
        self.assertEqual(state_b.stage, 1)


if __name__ == "__main__":
    unittest.main()
