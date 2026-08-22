from abc import ABC, abstractmethod
from typing import Literal, overload

from divergencesplitter.models import FrameContext
from divergencesplitter.rule import Condition


class ConditionBase(ABC):
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
        if type(result) is bool:
            return result
        if is_short_circuited and result is None:
            return None
        raise TypeError(f"condition must return a strict bool, got {result!r}")

    @abstractmethod
    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None: ...

    @abstractmethod
    def reset(self) -> None: ...


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


def reset_all(conditions: tuple[Condition, ...]) -> None:
    for condition in conditions:
        condition.reset()
