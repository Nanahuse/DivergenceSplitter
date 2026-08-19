import unittest

import numpy as np

from divergencesplitter.logic import (
    All,
    Any,
    FallingEdge,
    Hold,
    Not,
    RisingEdge,
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

    def test_consumes_all_even_after_false(self):
        consumed = []

        def values():
            for value in (True, False, True, True):
                consumed.append(value)
                yield value

        self.assertFalse(All().apply(values()))
        self.assertEqual(consumed, [True, False, True, True])

    def test_fetches_past_result_determined(self):
        def values():
            yield True
            yield False
            raise AssertionError(
                "All fetched an element after the result was determined"
            )

        with self.assertRaises(AssertionError):
            All().apply(values())

    def test_non_bool_element_raises(self):
        with self.assertRaises(TypeError):
            All().apply([True, 1, True])  # type: ignore

    def test_numpy_bool_element_rejected(self):
        with self.assertRaises(TypeError):
            All().apply([np.True_, True])  # type: ignore

    def test_invalid_element_after_false_raises(self):
        with self.assertRaises(TypeError):
            All().apply([False, "not a bool"])  # type: ignore


class AnyTest(unittest.TestCase):
    def test_empty_is_false(self):
        self.assertFalse(Any().apply([]))

    def test_any_true(self):
        self.assertTrue(Any().apply([False, False, True]))

    def test_all_false(self):
        self.assertFalse(Any().apply([False, False]))

    def test_consumes_all_even_after_true(self):
        consumed = []

        def values():
            for value in (False, True, False, False):
                consumed.append(value)
                yield value

        self.assertTrue(Any().apply(values()))
        self.assertEqual(consumed, [False, True, False, False])

    def test_fetches_past_result_determined(self):
        def values():
            yield False
            yield True
            raise AssertionError(
                "Any fetched an element after the result was determined"
            )

        with self.assertRaises(AssertionError):
            Any().apply(values())

    def test_non_bool_element_raises(self):
        with self.assertRaises(TypeError):
            Any().apply([False, 0, True])  # type: ignore

    def test_numpy_bool_element_rejected(self):
        with self.assertRaises(TypeError):
            Any().apply([np.False_, False])  # type: ignore

    def test_invalid_element_after_true_raises(self):
        with self.assertRaises(TypeError):
            Any().apply([True, "not a bool"])  # type: ignore


class NotTest(unittest.TestCase):
    def test_negation(self):
        self.assertFalse(Not().apply(True))
        self.assertTrue(Not().apply(False))

    def test_non_bool_raises(self):
        with self.assertRaises(TypeError):
            Not().apply(1)  # type: ignore

    def test_numpy_bool_rejected(self):
        with self.assertRaises(TypeError):
            Not().apply(np.True_)  # type: ignore

    def test_ambiguous_truthiness_array_rejected(self):
        with self.assertRaises(TypeError):
            Not().apply(np.array([True, False]))  # type: ignore


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

    def test_non_bool_input_rejected_and_state_unchanged(self):
        edge = RisingEdge()
        with self.assertRaises(TypeError):
            edge.step(1)  # type: ignore
        self.assertFalse(edge.step(False))
        self.assertTrue(edge.step(True))

    def test_numpy_bool_input_rejected(self):
        edge = RisingEdge()
        with self.assertRaises(TypeError):
            edge.step(np.True_)  # type: ignore


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

    def test_non_bool_input_rejected_and_state_unchanged(self):
        edge = FallingEdge()
        with self.assertRaises(TypeError):
            edge.step(1)  # type: ignore
        self.assertFalse(edge.step(True))
        self.assertTrue(edge.step(False))

    def test_numpy_bool_input_rejected(self):
        edge = FallingEdge()
        with self.assertRaises(TypeError):
            edge.step(np.False_)  # type: ignore


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

    def test_non_bool_input_rejected_before_mutation(self):
        hold = Hold(duration_nanoseconds=10)
        with self.assertRaises(TypeError):
            hold.step(1, t(0))  # type: ignore
        self.assertFalse(hold.step(True, t(0)))
        self.assertTrue(hold.step(True, t(10)))

    def test_numpy_bool_input_rejected(self):
        hold = Hold(duration_nanoseconds=10)
        with self.assertRaises(TypeError):
            hold.step(np.True_, t(0))  # type: ignore


if __name__ == "__main__":
    unittest.main()
