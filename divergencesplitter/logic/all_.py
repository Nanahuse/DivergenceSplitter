"""All: conjunction of boolean inputs."""

from collections.abc import Iterable


class All:
    """True when every input is ``True``; an empty input is ``True``.

    ``values`` is consumed lazily and evaluation stops at the first
    ``False``: later elements are never fetched or evaluated. This lets a
    generator short-circuit upstream evaluation once the result is
    determined.

    Each consumed element must be a strict ``bool``; any other type raises
    :class:`TypeError`. Elements after the decisive ``False`` are neither
    fetched nor validated.

    The short-circuit applies to result composition only: it does not mean a
    stateful operand's transition may be skipped. A ``Rule`` transitions every
    stateful node in its transition phase and uses ``apply`` only to compose
    the already-transitioned booleans.
    """

    def apply(self, values: Iterable[bool]) -> bool:
        for value in values:
            if type(value) is not bool:
                raise TypeError(f"value must be a strict bool, got {value!r}")
            if not value:
                return False
        return True
