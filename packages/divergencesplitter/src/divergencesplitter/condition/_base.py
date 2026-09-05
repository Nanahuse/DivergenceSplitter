from abc import ABC, abstractmethod
from typing import Literal, overload

from divergencesplitter.condition.interface import Condition, ConditionStatus
from divergencesplitter.frame.models import FrameContext


class ConditionBase(ABC):
    _status: ConditionStatus | None = None

    @property
    def status(self) -> ConditionStatus | None:
        """Typed outcome of the most recent evaluation, or ``None`` before one."""
        return self._status

    @property
    @abstractmethod
    def children(self) -> tuple[Condition, ...]:
        """Read-only child conditions in declaration order (leaves return ``()``)."""
        ...

    @overload
    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: Literal[False] = False,
    ) -> bool: ...

    @overload
    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: Literal[True],
    ) -> bool | None: ...

    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: bool = False,
    ) -> bool | None:
        result = self._evaluate(context, is_short_circuited=is_short_circuited)
        if is_short_circuited:
            self._status = ConditionStatus.SKIPPED
        if type(result) is bool:
            if not is_short_circuited:
                self._status = ConditionStatus.TRUE if result else ConditionStatus.FALSE
            return result
        if is_short_circuited and result is None:
            return None
        raise TypeError(f"condition must return a strict bool, got {result!r}")

    @abstractmethod
    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None: ...

    def reset(self) -> None:
        self._status = None
        self._reset_state()

    def _mark_skipped(self) -> None:
        self._status = ConditionStatus.SKIPPED
        for child in self.children:
            mark_skipped(child)

    @abstractmethod
    def _reset_state(self) -> None: ...


def evaluate_normal(condition: Condition, context: FrameContext) -> bool:
    result = condition.evaluate(context)
    if type(result) is not bool:
        raise TypeError(f"condition must return a strict bool, got {result!r}")
    return result


def evaluate_short(condition: Condition, context: FrameContext) -> None:
    result = condition.evaluate(context, is_short_circuited=True)
    if type(result) is not bool and result is not None:
        raise TypeError(
            "short-circuited condition must return a strict bool or None, "
            f"got {result!r}"
        )


def mark_skipped(condition: Condition) -> None:
    """Mark an unevaluated built-in subtree as short-circuited."""
    if isinstance(condition, ConditionBase):
        condition._mark_skipped()


def reset_all(conditions: tuple[Condition, ...]) -> None:
    for condition in conditions:
        condition.reset()
