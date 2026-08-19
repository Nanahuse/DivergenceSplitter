from collections.abc import Sequence

from divergencesplitter.models import MonotonicTime


class Then:
    """Matches ordered conditions within an inclusive deadline.

    At most one stage advances per call. Early pulses are not buffered, and a
    completed sequence remains true.
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
        snapshot = tuple(values)
        if len(snapshot) != self._step_count:
            raise ValueError(f"expected {self._step_count} values, got {len(snapshot)}")
        for value in snapshot:
            if type(value) is not bool:
                raise TypeError(f"value must be a strict bool, got {value!r}")
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
            if snapshot[0]:
                if self._step_count == 1:
                    self._completed = True
                    return True
                self._stage = 1
                self._start = now
                return False
            return False
        if snapshot[self._stage]:
            next_stage = self._stage + 1
            if next_stage == self._step_count:
                self._stage = 0
                self._start = None
                self._completed = True
                return True
            self._stage = next_stage
            return False
        return False
