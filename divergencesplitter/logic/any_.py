"""Any: disjunction of boolean inputs."""

from collections.abc import Iterable


class Any:
    """True when any input is ``True``; an empty input is ``False``."""

    def apply(self, values: Iterable[bool]) -> bool:
        return any(values)
