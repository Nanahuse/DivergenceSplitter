"""Condition contract.

The implementation contract is defined in the :class:`Condition` protocol
docstring.
"""

from typing import Literal, Protocol, overload

from divergencesplitter.models import FrameContext


class Condition(Protocol):
    """Rule condition tree node contract.

    Implementations evaluate ``context`` and return a strict ``bool`` for a
    normal evaluation (the default ``is_short_circuited=False``). A
    short-circuited evaluation (``is_short_circuited=True``) may return
    ``None``, but must still update every state required by future evaluations.
    Each instance owns its own state and updates required state on every call,
    even when short-circuited.
    ``reset`` restores the initial state and propagates to children.
    """

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
    ) -> bool | None: ...

    def reset(self) -> None: ...
