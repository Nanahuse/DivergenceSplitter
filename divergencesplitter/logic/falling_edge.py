"""FallingEdge: true-to-false transition detector."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FallingEdgeState:
    """Previous observation; ``None`` until the first baseline observation."""

    previous: bool | None


@dataclass(frozen=True)
class FallingEdge:
    """True exactly when the input transitions from ``True`` to ``False``.

    The first observation only establishes a baseline and never fires.
    """

    def initial_state(self) -> FallingEdgeState:
        return FallingEdgeState(previous=None)

    def step(
        self, value: bool, state: FallingEdgeState
    ) -> tuple[bool, FallingEdgeState]:
        previous = state.previous
        if previous is None:
            return (False, FallingEdgeState(previous=value))
        fired = previous and not value
        return (fired, FallingEdgeState(previous=value))
