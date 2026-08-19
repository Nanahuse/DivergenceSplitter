"""All: conjunction of boolean inputs."""

from collections.abc import Iterable


class All:
    """True when every input is ``True``; an empty input is ``True``.

    ``values`` is consumed in full before the result is composed, so every
    element is fetched and validated even after a ``False`` has been seen.

    Each element must be a strict ``bool``; any other type raises
    :class:`TypeError`.
    """

    def apply(self, values: Iterable[bool]) -> bool:
        snapshot = tuple(values)
        for value in snapshot:
            if type(value) is not bool:
                raise TypeError(f"value must be a strict bool, got {value!r}")
        return all(snapshot)
