from typing import Literal, Protocol, overload

from divergencesplitter.frame.models import FrameContext


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
