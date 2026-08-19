from collections.abc import Iterable


class All:
    def apply(self, values: Iterable[bool]) -> bool:
        snapshot = tuple(values)
        return all(snapshot)
