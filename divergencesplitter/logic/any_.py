"""Any: disjunction of boolean inputs."""

from collections.abc import Iterable


class Any:
    """True when any input is ``True``; an empty input is ``False``.

    ``values`` is consumed in full before the result is composed, so every
    element is fetched and validated even after a ``True`` has been seen.

    Each element must be a strict ``bool``; any other type raises
    :class:`TypeError`.
    """

    def apply(self, values: Iterable[bool]) -> bool:
        snapshot = tuple(values)
        for value in snapshot:
            if type(value) is not bool:
                raise TypeError(f"value must be a strict bool, got {value!r}")
        return any(snapshot)
