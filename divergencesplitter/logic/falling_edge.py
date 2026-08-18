"""FallingEdge: true-to-false transition detector."""


class FallingEdge:
    """True exactly when the input transitions from ``True`` to ``False``.

    The first observation only establishes a baseline and never fires. Each
    instance keeps its own previous observation; independent instances do not
    share history.

    ``value`` must be a strict ``bool``; any other type raises
    :class:`TypeError` before the previous observation is updated.
    """

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
