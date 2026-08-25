from divergencesplitter.condition._base import (
    ConditionBase,
    evaluate_normal,
    evaluate_short,
)
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class Not(ConditionBase):
    def __init__(self, condition: Condition) -> None:
        self._condition = condition

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if is_short_circuited:
            evaluate_short(self._condition, context)
            return None
        return not evaluate_normal(self._condition, context)

    def reset(self) -> None:
        self._condition.reset()
