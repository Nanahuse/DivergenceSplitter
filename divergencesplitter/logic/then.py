"""Then: ordered sequence of conditions with a deadline."""

from collections.abc import Sequence
from dataclasses import dataclass

from divergencesplitter.models import MonotonicTime


@dataclass(frozen=True)
class ThenState:
    """Progress of an in-flight ``Then`` sequence.

    ``stage`` counts the conditions satisfied so far in the current attempt.
    ``start`` is the deadline reference, set when the first condition becomes
    ``True``. ``completed`` latches once every condition has been satisfied in
    order within the deadline.
    """

    stage: int
    start: MonotonicTime | None
    completed: bool


@dataclass(frozen=True)
class Then:
    """True once ``step_count`` conditions are satisfied in order in time.

    The deadline is measured from the observation that first satisfies the
    leading condition. Each call advances the current stage by at most one, so
    later conditions satisfied early in the same observation are ignored. The
    deadline is inclusive: ``elapsed <= within_nanoseconds`` keeps the attempt
    alive, while ``elapsed > within_nanoseconds`` discards it and allows a new
    attempt to begin from the leading condition of the same observation. Once
    completed, the result stays ``True`` until the state is reset.
    """

    step_count: int
    within_nanoseconds: int

    def __post_init__(self) -> None:
        if self.step_count < 1:
            raise ValueError(f"step_count must be at least 1: {self.step_count}")
        if self.within_nanoseconds < 0:
            raise ValueError(
                f"within_nanoseconds must be non-negative: {self.within_nanoseconds}"
            )

    def initial_state(self) -> ThenState:
        return ThenState(stage=0, start=None, completed=False)

    def step(
        self, values: Sequence[bool], now: MonotonicTime, state: ThenState
    ) -> tuple[bool, ThenState]:
        if len(values) != self.step_count:
            raise ValueError(f"expected {self.step_count} values, got {len(values)}")
        if state.completed:
            return (True, state)
        if state.start is not None:
            if now < state.start:
                raise ValueError(
                    f"now moved backwards from {state.start.nanoseconds} "
                    f"to {now.nanoseconds}"
                )
            if now.nanoseconds - state.start.nanoseconds > self.within_nanoseconds:
                state = ThenState(stage=0, start=None, completed=False)
        if state.start is None:
            if values[0]:
                if self.step_count == 1:
                    return (True, ThenState(stage=0, start=None, completed=True))
                return (False, ThenState(stage=1, start=now, completed=False))
            return (False, state)
        if values[state.stage]:
            next_stage = state.stage + 1
            if next_stage == self.step_count:
                return (True, ThenState(stage=0, start=None, completed=True))
            return (
                False,
                ThenState(stage=next_stage, start=state.start, completed=False),
            )
        return (False, state)
