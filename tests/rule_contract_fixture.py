"""Static type-check fixture for the Rule / Condition / Action contracts.

This module is only exercised by the type checker (``ty check .``). It holds
no runtime assertions. If the public contracts drift, ``ty`` reports the
break here before any runtime consumer exists.
"""

from typing import Literal, overload

from divergencesplitter.models import FrameContext
from divergencesplitter.rule import Action, Condition, Rule


class ConstantCondition:
    def __init__(self, result: bool) -> None:
        self._result = result

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
        if is_short_circuited:
            return None
        return self._result

    def reset(self) -> None:
        pass


def expect_bool(value: bool) -> None:
    pass


def expect_optional(value: bool | None) -> None:
    pass


def exercise_evaluate(context: FrameContext) -> None:
    condition: Condition = ConstantCondition(True)
    expect_bool(condition.evaluate(context))
    expect_bool(condition.evaluate(context, is_short_circuited=False))
    expect_optional(condition.evaluate(context, is_short_circuited=True))


def exercise_rule(context: FrameContext) -> Action | None:
    condition: Condition = ConstantCondition(True)
    rule = Rule(
        condition=condition,
        action=Action(scenario_id="scenario", target_id="game", operation="Split"),
    )
    rule.reset()
    return rule.evaluate(context)


def exercise_action(action: Action) -> tuple[str, str, str]:
    return action.scenario_id, action.target_id, action.operation
