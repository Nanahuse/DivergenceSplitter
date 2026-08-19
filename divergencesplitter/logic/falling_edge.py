class FallingEdge:
    """Detects true-to-false transitions; the first value sets the baseline."""

    def __init__(self) -> None:
        self._previous: bool | None = None

    def step(self, value: bool) -> bool:
        if type(value) is not bool:
            raise TypeError(f"value must be a strict bool, got {value!r}")
        previous = self._previous
        self._previous = value
        if previous is None:
            return False
        return previous and not value
