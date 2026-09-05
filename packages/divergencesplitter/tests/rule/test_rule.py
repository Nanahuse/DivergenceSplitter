import unittest
from typing import Literal, cast, overload

import numpy as np
from divergencesplitter.clock import MonotonicTime
from divergencesplitter.frame.models import Frame, FrameContext
from divergencesplitter.rule import Action, Rule

EPOCH = MonotonicTime(nanoseconds=0)


def make_context() -> FrameContext:
    return FrameContext(
        frame=Frame(image=np.zeros((2, 3), dtype=np.uint8), captured_at=EPOCH),
        now=EPOCH,
    )


class RecordingCondition:
    def __init__(self, result: bool | None) -> None:
        self.result = result
        self.calls: list[bool] = []
        self.resets = 0

    @property
    def children(self) -> tuple:
        return ()

    def inject(self, result: object) -> None:
        self.result = cast("bool | None", result)

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
        return self.result

    def reset(self) -> None:
        self.resets += 1


def make_action() -> Action:
    return Action(operation="split")


class RuleEvaluateTest(unittest.TestCase):
    def test_returns_action_when_condition_is_true(self) -> None:
        action = make_action()
        rule = Rule(condition=RecordingCondition(True), action=action)
        self.assertIs(rule.evaluate(make_context()), action)

    def test_returns_none_when_condition_is_false(self) -> None:
        rule = Rule(condition=RecordingCondition(False), action=make_action())
        self.assertIsNone(rule.evaluate(make_context()))

    def test_raises_type_error_when_condition_returns_none(self) -> None:
        condition = RecordingCondition(True)
        condition.inject(None)
        rule = Rule(condition=condition, action=make_action())
        with self.assertRaises(TypeError):
            rule.evaluate(make_context())

    def test_raises_type_error_when_condition_returns_int(self) -> None:
        condition = RecordingCondition(True)
        condition.inject(1)
        rule = Rule(condition=condition, action=make_action())
        with self.assertRaises(TypeError):
            rule.evaluate(make_context())

    def test_raises_type_error_when_condition_returns_numpy_bool(self) -> None:
        condition = RecordingCondition(True)
        condition.inject(np.bool_(True))
        rule = Rule(condition=condition, action=make_action())
        with self.assertRaises(TypeError):
            rule.evaluate(make_context())

    def test_root_condition_is_evaluated_without_short_circuit(self) -> None:
        condition = RecordingCondition(True)
        rule = Rule(condition=condition, action=make_action())
        rule.evaluate(make_context())
        self.assertEqual(condition.calls, [False])


class RuleResetTest(unittest.TestCase):
    def test_reset_propagates_to_condition(self) -> None:
        condition = RecordingCondition(True)
        action = make_action()
        rule = Rule(condition=condition, action=action)
        rule.reset()
        self.assertEqual(condition.resets, 1)
        self.assertIs(rule.action, action)


if __name__ == "__main__":
    unittest.main()
