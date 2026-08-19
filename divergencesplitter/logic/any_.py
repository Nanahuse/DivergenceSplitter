from collections.abc import Iterable


class Any:
    def apply(self, values: Iterable[bool]) -> bool:
        snapshot = tuple(values)
        return any(snapshot)
