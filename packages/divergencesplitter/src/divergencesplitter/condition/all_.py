from divergencesplitter.condition._base import (
    ConditionBase,
    evaluate_normal,
    evaluate_short,
    reset_all,
)
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class All(ConditionBase):
    def __init__(self, *conditions: Condition) -> None:
        self._conditions = conditions

    @property
    def children(self) -> tuple[Condition, ...]:
        return self._conditions

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if is_short_circuited:
            for condition in self._conditions:
                evaluate_short(condition, context)
            return None
        result = True
        for condition in self._conditions:
            if result:
                result = evaluate_normal(condition, context)
            else:
                evaluate_short(condition, context)
        return result

    def reset(self) -> None:
        reset_all(self._conditions)
