from divergencesplitter.condition._base import ConditionBase, evaluate_normal
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class Once(ConditionBase):
    def __init__(self, condition: Condition) -> None:
        self._condition = condition
        self._completed = False

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if self._completed:
            return None if is_short_circuited else True
        current = evaluate_normal(self._condition, context)
        if current:
            self._completed = True
        return None if is_short_circuited else current

    def reset(self) -> None:
        self._completed = False
        self._condition.reset()
