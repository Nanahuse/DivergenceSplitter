from divergencesplitter.condition._base import (
    ConditionBase,
    evaluate_normal,
    evaluate_short,
    reset_all,
)
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class ResetWhen(ConditionBase):
    def __init__(self, condition: Condition, reset_condition: Condition) -> None:
        self._condition = condition
        self._reset_condition = reset_condition

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if is_short_circuited:
            evaluate_short(self._condition, context)
            result = None
        else:
            result = evaluate_normal(self._condition, context)

        should_reset = evaluate_normal(self._reset_condition, context)
        if should_reset:
            self.reset()
        return result

    def reset(self) -> None:
        reset_all((self._condition, self._reset_condition))
