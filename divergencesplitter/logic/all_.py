"""All: conjunction of boolean inputs."""

from collections.abc import Iterable


class All:
    """True when every input is ``True``; an empty input is ``True``."""

    def apply(self, values: Iterable[bool]) -> bool:
        return all(values)
