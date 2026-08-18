"""All: conjunction of boolean inputs."""

from collections.abc import Iterable


class All:
    """True when every input is ``True``; an empty input is ``True``.

    ``values`` is consumed lazily and evaluation stops at the first
    ``False``: later elements are never fetched or evaluated. This lets a
    generator short-circuit upstream evaluation once the result is
    determined.
    """

    def apply(self, values: Iterable[bool]) -> bool:
        return all(values)
