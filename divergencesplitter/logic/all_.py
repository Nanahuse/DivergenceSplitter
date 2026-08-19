from collections.abc import Iterable


class All:
    def apply(self, values: Iterable[bool]) -> bool:
        snapshot = tuple(values)
        for value in snapshot:
            if type(value) is not bool:
                raise TypeError(f"value must be a strict bool, got {value!r}")
        return all(snapshot)
