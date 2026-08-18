"""Hold: minimum-duration latch."""

from dataclasses import dataclass

from divergencesplitter.models import MonotonicTime


@dataclass(frozen=True)
class HoldState:
    """Moment the input became ``True``, or ``None`` while not held."""

    start: MonotonicTime | None


@dataclass(frozen=True)
class Hold:
    """True once the input has stayed ``True`` for ``duration_nanoseconds``.

    Once satisfied it stays ``True`` while the input remains ``True``. A
    ``False`` input releases and re-arms the hold. A zero duration is
    satisfied by the first ``True`` observation.
    """

    duration_nanoseconds: int

    def __post_init__(self) -> None:
        if self.duration_nanoseconds < 0:
            raise ValueError(
                f"duration_nanoseconds must be non-negative: {self.duration_nanoseconds}"
            )

    def initial_state(self) -> HoldState:
        return HoldState(start=None)

    def step(
        self, value: bool, now: MonotonicTime, state: HoldState
    ) -> tuple[bool, HoldState]:
        if state.start is not None and now < state.start:
            raise ValueError(
                f"now moved backwards from {state.start.nanoseconds} to {now.nanoseconds}"
            )
        if not value:
            return (False, HoldState(start=None))
        start = state.start if state.start is not None else now
        elapsed = now.nanoseconds - start.nanoseconds
        return (elapsed >= self.duration_nanoseconds, HoldState(start=start))
