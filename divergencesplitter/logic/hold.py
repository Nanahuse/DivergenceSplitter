"""Hold: minimum-duration latch."""

from divergencesplitter.models import MonotonicTime


class Hold:
    """True once the input has stayed ``True`` for ``duration_nanoseconds``.

    Once satisfied it stays ``True`` while the input remains ``True``. A
    ``False`` input releases and re-arms the hold. A zero duration is satisfied
    by the first ``True`` observation. Each instance keeps its own start time;
    independent instances do not share state.
    """

    def __init__(self, duration_nanoseconds: int) -> None:
        if duration_nanoseconds < 0:
            raise ValueError(
                f"duration_nanoseconds must be non-negative: {duration_nanoseconds}"
            )
        self._duration_nanoseconds = duration_nanoseconds
        self._start: MonotonicTime | None = None

    def step(self, value: bool, now: MonotonicTime) -> bool:
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
