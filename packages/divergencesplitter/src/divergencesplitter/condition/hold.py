from divergencesplitter.clock import MonotonicTime
from divergencesplitter.condition._base import ConditionBase, evaluate_normal
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class Hold(ConditionBase):
    def __init__(self, condition: Condition, duration_nanoseconds: int) -> None:
        if duration_nanoseconds < 0:
            raise ValueError("duration_nanoseconds must be a non-negative int")
        self._condition = condition
        self._duration_nanoseconds = duration_nanoseconds
        self._started_at: MonotonicTime | None = None

    @property
    def children(self) -> tuple[Condition, ...]:
        return (self._condition,)

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        current = evaluate_normal(self._condition, context)
        if self._started_at is not None and context.now < self._started_at:
            raise ValueError("monotonic time moved backwards")
        if not current:
            self._started_at = None
            result = False
        else:
            if self._started_at is None:
                self._started_at = context.now
            elapsed = context.now.nanoseconds - self._started_at.nanoseconds
            result = elapsed >= self._duration_nanoseconds
        return None if is_short_circuited else result

    def reset(self) -> None:
        self._started_at = None
        self._condition.reset()
