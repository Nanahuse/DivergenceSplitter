"""Then: ordered sequence of conditions with a deadline."""

from collections.abc import Sequence

from divergencesplitter.models import MonotonicTime


class Then:
    """True once ``step_count`` conditions are satisfied in order in time.

    The deadline is measured from the observation that first satisfies the
    leading condition. Each call advances the current stage by at most one, so
    later conditions satisfied early in the same observation are ignored. The
    deadline is inclusive: ``elapsed <= within_nanoseconds`` keeps the attempt
    alive, while ``elapsed > within_nanoseconds`` discards it and allows a new
    attempt to begin from the leading condition of the same observation. Once
    completed, the result stays ``True`` until the instance is discarded. Each
    instance keeps its own progress; independent instances do not share state.
    """

    def __init__(self, step_count: int, within_nanoseconds: int) -> None:
        if step_count < 1:
            raise ValueError(f"step_count must be at least 1: {step_count}")
        if within_nanoseconds < 0:
            raise ValueError(
                f"within_nanoseconds must be non-negative: {within_nanoseconds}"
            )
        self._step_count = step_count
        self._within_nanoseconds = within_nanoseconds
        self._stage = 0
        self._start: MonotonicTime | None = None
        self._completed = False

    def step(self, values: Sequence[bool], now: MonotonicTime) -> bool:
        if len(values) != self._step_count:
            raise ValueError(f"expected {self._step_count} values, got {len(values)}")
        if self._completed:
            return True
        if self._start is not None:
            if now < self._start:
                raise ValueError(
                    f"now moved backwards from {self._start.nanoseconds} "
                    f"to {now.nanoseconds}"
                )
            if now.nanoseconds - self._start.nanoseconds > self._within_nanoseconds:
                self._stage = 0
                self._start = None
        if self._start is None:
            if values[0]:
                if self._step_count == 1:
                    self._completed = True
                    return True
                self._stage = 1
                self._start = now
                return False
            return False
        if values[self._stage]:
            next_stage = self._stage + 1
            if next_stage == self._step_count:
                self._stage = 0
                self._start = None
                self._completed = True
                return True
            self._stage = next_stage
            return False
        return False
