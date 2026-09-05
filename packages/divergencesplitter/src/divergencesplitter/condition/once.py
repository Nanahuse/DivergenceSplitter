from divergencesplitter.condition._base import (
    ConditionBase,
    evaluate_normal,
    mark_skipped,
)
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class Once(ConditionBase):
    def __init__(self, condition: Condition) -> None:
        self._condition = condition
        self._completed = False

    @property
    def children(self) -> tuple[Condition, ...]:
        return (self._condition,)

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if self._completed:
            mark_skipped(self._condition)
            return None if is_short_circuited else True
        current = evaluate_normal(self._condition, context)
        if current:
            self._completed = True
        return None if is_short_circuited else current

    def _reset_state(self) -> None:
        self._completed = False
        self._condition.reset()
