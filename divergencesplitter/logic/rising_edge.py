"""RisingEdge: false-to-true transition detector."""


class RisingEdge:
    """True exactly when the input transitions from ``False`` to ``True``.

    The first observation only establishes a baseline and never fires. Each
    instance keeps its own previous observation; independent instances do not
    share history.
    """

    def __init__(self) -> None:
        self._previous: bool | None = None

    def step(self, value: bool) -> bool:
        previous = self._previous
        self._previous = value
        if previous is None:
            return False
        return not previous and value
