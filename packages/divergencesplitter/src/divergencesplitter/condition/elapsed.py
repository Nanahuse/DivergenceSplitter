from divergencesplitter.clock import MonotonicTime
from divergencesplitter.condition._base import ConditionBase
from divergencesplitter.condition.interface import Condition
from divergencesplitter.frame.models import FrameContext


class Elapsed(ConditionBase):
    def __init__(self, duration_nanoseconds: int) -> None:
        if duration_nanoseconds < 0:
            raise ValueError("duration_nanoseconds must be a non-negative int")
        self._duration_nanoseconds = duration_nanoseconds
        self._started_at: MonotonicTime | None = None
        self._completed = False

    @property
    def children(self) -> tuple[Condition, ...]:
        return ()

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if self._completed:
            return None if is_short_circuited else True
        if self._started_at is not None and context.now < self._started_at:
            raise ValueError("monotonic time moved backwards")
        if self._started_at is None:
            self._started_at = context.now
        elapsed = context.now.nanoseconds - self._started_at.nanoseconds
        if elapsed >= self._duration_nanoseconds:
            self._completed = True
        return None if is_short_circuited else self._completed

    def _reset_state(self) -> None:
        self._started_at = None
        self._completed = False
