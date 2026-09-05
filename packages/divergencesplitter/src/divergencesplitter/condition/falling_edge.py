from divergencesplitter.condition._base import ConditionBase, evaluate_normal
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class FallingEdge(ConditionBase):
    def __init__(self, condition: Condition) -> None:
        self._condition = condition
        self._previous: bool | None = None

    @property
    def children(self) -> tuple[Condition, ...]:
        return (self._condition,)

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        current = evaluate_normal(self._condition, context)
        previous = self._previous
        self._previous = current
        fired = previous is not None and previous and not current
        return None if is_short_circuited else fired

    def _reset_state(self) -> None:
        self._previous = None
        self._condition.reset()
