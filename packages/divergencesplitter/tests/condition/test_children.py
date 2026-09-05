import unittest

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
    ResetWhen,
    RisingEdge,
    Then,
)
from divergencesplitter.detector import MeanBrightnessDetector


class _Leaf:
    pass


_LEAF = _Leaf()


class ChildrenExposureTest(unittest.TestCase):
    def test_leaf_conditions_expose_an_empty_tuple(self) -> None:
        self.assertEqual(Elapsed(0).children, ())
        self.assertEqual(Detected(MeanBrightnessDetector(), 0.0).children, ())

    def test_single_child_conditions_expose_a_one_element_tuple(self) -> None:
        child = Elapsed(0)
        self.assertEqual(Not(child).children, (child,))
        self.assertEqual(Hold(child, 5).children, (child,))
        self.assertEqual(Once(child).children, (child,))
        self.assertEqual(Nth(child, 1).children, (child,))
        self.assertEqual(RisingEdge(child).children, (child,))
        self.assertEqual(FallingEdge(child).children, (child,))

    def test_multi_child_conditions_expose_children_in_declaration_order(self) -> None:
        first = Elapsed(0)
        second = Elapsed(1)
        third = Elapsed(2)
        self.assertEqual(All(first, second, third).children, (first, second, third))
        self.assertEqual(Any(first, second, third).children, (first, second, third))
        self.assertEqual(
            Then(first, second, third, within_nanoseconds=5).children,
            (first, second, third),
        )

    def test_reset_when_exposes_declaration_order_including_reset_condition(
        self,
    ) -> None:
        condition = Elapsed(0)
        reset_condition = Elapsed(1)
        self.assertEqual(
            ResetWhen(condition, reset_condition).children,
            (condition, reset_condition),
        )

    def test_children_reflect_nesting_but_do_not_evaluate_or_reset(self) -> None:
        inner = Elapsed(0)
        outer = All(Not(inner))
        nested = outer.children[0]
        self.assertIsInstance(nested, Not)
        self.assertEqual(nested.children, (inner,))

    def test_children_exposes_structurally_shared_instances(self) -> None:
        shared = Elapsed(0)
        condition = All(shared, Not(shared))
        self.assertIs(condition.children[0], shared)
        self.assertIs(condition.children[1].children[0], shared)


if __name__ == "__main__":
    unittest.main()
