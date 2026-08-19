from divergencesplitter.models import MonotonicTime


class Hold:
    """Becomes true after a continuous true interval; false resets it."""

    def __init__(self, duration_nanoseconds: int) -> None:
        if duration_nanoseconds < 0:
            raise ValueError(
                f"duration_nanoseconds must be non-negative: {duration_nanoseconds}"
            )
        self._duration_nanoseconds = duration_nanoseconds
        self._start: MonotonicTime | None = None

    def step(self, value: bool, now: MonotonicTime) -> bool:
        if type(value) is not bool:
            raise TypeError(f"value must be a strict bool, got {value!r}")
        if self._start is not None and now < self._start:
            raise ValueError(
                f"now moved backwards from {self._start.nanoseconds} to {now.nanoseconds}"
            )
        if not value:
            self._start = None
            return False
        start = self._start if self._start is not None else now
        self._start = start
        elapsed = now.nanoseconds - start.nanoseconds
        return elapsed >= self._duration_nanoseconds
