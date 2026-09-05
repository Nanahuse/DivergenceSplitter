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

    @property
    def children(self) -> tuple[Condition, ...]:
        return (self._condition, self._reset_condition)

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        should_reset = evaluate_normal(self._reset_condition, context)
        if should_reset:
            self.reset()

        if is_short_circuited:
            evaluate_short(self._condition, context)
            return None
        return evaluate_normal(self._condition, context)

    def _reset_state(self) -> None:
        reset_all((self._condition, self._reset_condition))
