from typing import Literal, Protocol, overload

from divergencesplitter.frame.models import FrameContext


class Condition(Protocol):
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
