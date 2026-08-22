from divergencesplitter.condition._base import (
    ConditionBase,
    evaluate_normal,
    evaluate_short,
    reset_all,
)
from divergencesplitter.models import FrameContext, MonotonicTime
from divergencesplitter.rule import Condition


class Then(ConditionBase):
    def __init__(self, *conditions: Condition, within_nanoseconds: int) -> None:
        if not conditions:
            raise ValueError("Then requires at least one condition")
        if type(within_nanoseconds) is not int or within_nanoseconds < 0:
            raise ValueError("within_nanoseconds must be a non-negative int")
        self._conditions = conditions
        self._within_nanoseconds = within_nanoseconds
        self._index = 0
        self._started_at: MonotonicTime | None = None
        self._completed = False

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if self._completed:
            for condition in self._conditions:
                evaluate_short(condition, context)
            return None if is_short_circuited else True
        if self._started_at is not None:
            if context.now < self._started_at:
                raise ValueError("monotonic time moved backwards")
            elapsed = context.now.nanoseconds - self._started_at.nanoseconds
            if elapsed > self._within_nanoseconds:
                self._index = 0
                self._started_at = None
        current = False
        for index, condition in enumerate(self._conditions):
            if index == self._index:
                current = evaluate_normal(condition, context)
            else:
                evaluate_short(condition, context)
        fired = False
        if current:
            if self._index == 0 and len(self._conditions) > 1:
                self._started_at = context.now
            self._index += 1
            if self._index == len(self._conditions):
                self._completed = True
                self._index = 0
                self._started_at = None
                fired = True
        return None if is_short_circuited else fired

    def reset(self) -> None:
        self._index = 0
        self._started_at = None
        self._completed = False
        reset_all(self._conditions)
