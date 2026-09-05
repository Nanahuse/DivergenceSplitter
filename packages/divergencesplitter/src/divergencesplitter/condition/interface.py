from enum import Enum, auto
from typing import Literal, Protocol, overload, runtime_checkable

from divergencesplitter.frame.models import FrameContext


class ConditionStatus(Enum):
    """Typed outcome of the most recent condition evaluation.

    ``SKIPPED`` marks a condition whose result was not used because a parent
    short-circuited it. The absence of a status (``None``) means the condition
    has not been evaluated since it started or was last reset.
    """

    TRUE = auto()
    FALSE = auto()
    SKIPPED = auto()


@runtime_checkable
class ObservableCondition(Protocol):
    @property
    def status(self) -> ConditionStatus | None:
        """Latest typed evaluation outcome, or ``None`` after reset."""
        ...


class Condition(Protocol):
    @property
    def children(self) -> tuple[Condition, ...]:
        """Read-only child conditions in declaration order.

        Leaf conditions return an empty tuple. This exposes structure for
        display only; it does not perform evaluation, reset, or state changes.
        """
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
        """Update state needed by future evaluations even when short-circuited."""
        ...

    def reset(self) -> None: ...
