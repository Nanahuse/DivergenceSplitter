from divergencesplitter.condition._base import ConditionBase, evaluate_normal
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class Nth(ConditionBase):
    def __init__(self, condition: Condition, count: int) -> None:
        if count < 1:
            raise ValueError("count must be a positive int")
        self._condition = condition
        self._count = count
        self._observed = 0
        self._completed = False

    @property
    def children(self) -> tuple[Condition, ...]:
        return (self._condition,)

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if self._completed:
            return None if is_short_circuited else False
        current = evaluate_normal(self._condition, context)
        fired = False
        if current:
            self._observed += 1
            if self._observed == self._count:
                self._completed = True
                fired = True
        return None if is_short_circuited else fired

    def reset(self) -> None:
        self._observed = 0
        self._completed = False
        self._condition.reset()
