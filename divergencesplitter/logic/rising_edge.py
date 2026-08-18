"""RisingEdge: false-to-true transition detector."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RisingEdgeState:
    """Previous observation; ``None`` until the first baseline observation."""

    previous: bool | None


@dataclass(frozen=True)
class RisingEdge:
    """True exactly when the input transitions from ``False`` to ``True``.

    The first observation only establishes a baseline and never fires.
    """

    def initial_state(self) -> RisingEdgeState:
        return RisingEdgeState(previous=None)

    def step(self, value: bool, state: RisingEdgeState) -> tuple[bool, RisingEdgeState]:
        previous = state.previous
        if previous is None:
            return (False, RisingEdgeState(previous=value))
        fired = not previous and value
        return (fired, RisingEdgeState(previous=value))
