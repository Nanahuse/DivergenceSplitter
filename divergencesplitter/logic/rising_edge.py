class RisingEdge:
    """Detects false-to-true transitions; the first value sets the baseline."""

    def __init__(self) -> None:
        self._previous: bool | None = None

    def step(self, value: bool) -> bool:
        previous = self._previous
        self._previous = value
        if previous is None:
            return False
        return not previous and value
