from divergencesplitter.condition._base import ConditionBase, evaluate_normal
from divergencesplitter.models import FrameContext
from divergencesplitter.rule import Condition


class RisingEdge(ConditionBase):
    def __init__(self, condition: Condition) -> None:
        self._condition = condition
        self._previous: bool | None = None

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        current = evaluate_normal(self._condition, context)
        previous = self._previous
        self._previous = current
        fired = previous is not None and not previous and current
        return None if is_short_circuited else fired

    def reset(self) -> None:
        self._previous = None
        self._condition.reset()
