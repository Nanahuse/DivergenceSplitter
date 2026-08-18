"""Any: disjunction of boolean inputs."""

from collections.abc import Iterable


class Any:
    """True when any input is ``True``; an empty input is ``False``.

    ``values`` is consumed lazily and evaluation stops at the first
    ``True``: later elements are never fetched or evaluated. This lets a
    generator short-circuit upstream evaluation once the result is
    determined.
    """

    def apply(self, values: Iterable[bool]) -> bool:
        return any(values)
